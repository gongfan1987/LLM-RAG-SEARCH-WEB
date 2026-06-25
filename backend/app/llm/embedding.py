"""Qwen3-Embedding 文本向量化：封装 langchain-openai 的 OpenAIEmbeddings。

对接 OpenAI 兼容的 embedding 接口，默认走 DashScope 兼容模式的 text-embedding-v4
（基于 Qwen3-Embedding 的模型），也可把 base_url / model 指向自托管的 Qwen3-Embedding 服务。

只负责把文本转成向量，不感知向量库 / RAG 业务（与 MilvusStore 解耦，编排由调用方完成）。
放在 app/llm 而非 utils，是为了把 langchain 的使用收敛在 LLM 组件内（utils 保持无 langchain 依赖）。
"""
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings, get_settings


class EmbeddingError(Exception):
    """向量化失败的统一异常，避免把 langchain / openai 的底层异常直接抛给调用方。"""


class EmbeddingClient:
    """文本向量化封装：把查询/文档转成向量，供 MilvusStore 等下游使用。

    用法：
        emb = get_embedding_client()
        qv = emb.embed_query("今天的天气怎么样")
        dvs = emb.embed_documents(["文档1", "文档2"])

    依赖：langchain-openai。底层 embeddings 可通过 _embeddings 注入，便于测试时替换。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        batch_size: int = 10,
        timeout: float = 15.0,
        max_retries: int = 1,
        *,
        _embeddings: OpenAIEmbeddings | None = None,
    ) -> None:
        self._batch_size = max(1, batch_size)
        self._embeddings = _embeddings or OpenAIEmbeddings(
            api_key=api_key,
            base_url=base_url,
            model=model,
            # 关闭基于 tiktoken 的客户端切分，按原文直接请求 /embeddings，兼容非 OpenAI 模型。
            check_embedding_ctx_length=False,
            # 显式超时与少重试：避免冷启动/限流时按 SDK 默认（可达数百秒）死等。
            timeout=timeout,
            max_retries=max_retries,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "EmbeddingClient":
        if not settings.embedding_configured:
            raise EmbeddingError("Embedding 未配置：请设置 EMBEDDING_API_KEY 与 EMBEDDING_MODEL_NAME")
        return cls(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model_name,
            batch_size=settings.embedding_batch_size,
            timeout=settings.embedding_timeout,
            max_retries=settings.embedding_max_retries,
        )

    def embed_query(self, text: str) -> list[float]:
        """把单条查询文本转成向量。"""
        try:
            return self._embeddings.embed_query(text)
        except Exception as exc:  # noqa: BLE001 统一包装底层异常
            raise EmbeddingError(f"向量化查询失败: {exc}") from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """把多条文档文本批量转成向量；按 batch_size 分批，避免超过服务端单批上限。"""
        items = list(texts)
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(items), self._batch_size):
                batch = items[start : start + self._batch_size]
                vectors.extend(self._embeddings.embed_documents(batch))
        except Exception as exc:  # noqa: BLE001 统一包装底层异常
            raise EmbeddingError(f"向量化文档失败: {exc}") from exc
        return vectors


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    """返回进程级单例 Embedding 客户端；未配置时抛出 EmbeddingError。"""
    return EmbeddingClient.from_settings(get_settings())
