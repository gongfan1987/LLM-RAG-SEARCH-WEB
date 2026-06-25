"""把历史对话消息自动索引进 Milvus：embedding 后写入向量库，供后续检索（RAG）使用。

编排两个技术组件——EmbeddingClient（app.llm，文本→向量）与 MilvusStore（app.utils，向量库），
并决定索引哪些字段、用什么主键（复用 chat_messages.id，便于检索命中后映射回原消息）、
何时建集合。属于业务编排，故放 service 层。

降级原则：embedding 或 milvus 未配置时整体 no-op；任一步失败仅记录日志并跳过，
绝不影响主对话流程——索引是检索的旁路收益，不能因它中断回复。
"""
import logging

from app.core.config import get_settings
from app.llm import get_embedding_client
from app.utils.milvus import get_milvus_client

logger = logging.getLogger(__name__)

# 集合是否已确保存在；进程内只需建一次，避免每次索引都多发一次 has_collection RPC。
_collection_ready = False


def index_messages(items: list[dict]) -> int:
    """把若干条消息索引进 Milvus，返回成功索引的条数；不可用或失败时返回 0（不抛出）。

    items: 每条形如 {"id": int, "session_id": int, "role": str, "text": str}。
    """
    settings = get_settings()
    if not (settings.embedding_configured and settings.milvus_configured):
        return 0
    records = [it for it in items if it.get("text")]
    if not records:
        return 0
    try:
        vectors = get_embedding_client().embed_documents([it["text"] for it in records])
        store = get_milvus_client()
        # 维度优先用配置（MILVUS_DIM），未配置（0）时按实际 embedding 输出维度推导。
        _ensure_collection(store, settings.milvus_dim or len(vectors[0]))
        data = [
            {
                "id": it["id"],
                "vector": vec,
                "text": it["text"],
                "role": it["role"],
                "session_id": it["session_id"],
            }
            for it, vec in zip(records, vectors)
        ]
        store.insert(data)
        return len(data)
    except Exception as exc:  # noqa: BLE001 索引是旁路收益，任何失败都不能影响主对话流程
        logger.warning("对话索引进 Milvus 失败，已跳过: %s", exc)
        return 0


def _ensure_collection(store, dim: int) -> None:
    global _collection_ready
    if not _collection_ready:
        store.ensure_collection(dim)
        _collection_ready = True
