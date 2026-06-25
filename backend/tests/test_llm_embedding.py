"""app/llm/embedding.py 单测：查询/文档向量化、错误包装与配置校验。

mock 说明：
- 用 FakeEmbeddings 替身注入 EmbeddingClient，不触达真实 embedding 服务、不发网络请求，
  并记录入参，便于断言透传。
- settings 用 Settings(...) 直接构造，不依赖真实 .env。
"""
import pytest

from app.core.config import Settings
from app.llm.embedding import EmbeddingClient, EmbeddingError


class FakeEmbeddings:
    """记录调用入参的伪 OpenAIEmbeddings；可设置 error 模拟失败。"""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.query_calls = []
        self.doc_calls = []

    def embed_query(self, text):
        if self.error:
            raise self.error
        self.query_calls.append(text)
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        if self.error:
            raise self.error
        self.doc_calls.append(list(texts))
        return [[0.1] for _ in texts]  # 每条输入对应一个向量


def _client(embeddings):
    return EmbeddingClient(api_key="k", base_url="http://x", model="m", _embeddings=embeddings)


def test_查询向量化透传文本并返回向量():
    fake = FakeEmbeddings()
    vec = _client(fake).embed_query("今天几号")
    assert fake.query_calls == ["今天几号"]
    assert vec == [0.1, 0.2, 0.3]


def test_文档向量化透传列表并返回多条向量():
    fake = FakeEmbeddings()
    vecs = _client(fake).embed_documents(["文档1", "文档2"])
    assert fake.doc_calls == [["文档1", "文档2"]]
    assert vecs == [[0.1], [0.1]]


def test_文档向量化超过批量上限时分批请求():
    # batch_size=2，传入 5 条 → 应分 3 批（2+2+1），避免一次性超过服务端上限
    fake = FakeEmbeddings()
    client = EmbeddingClient(
        api_key="k", base_url="http://x", model="m", batch_size=2, _embeddings=fake
    )
    vecs = client.embed_documents(["a", "b", "c", "d", "e"])
    assert [len(call) for call in fake.doc_calls] == [2, 2, 1]
    assert len(vecs) == 5


def test_查询向量化失败时包装为EmbeddingError():
    fake = FakeEmbeddings(error=RuntimeError("network down"))
    with pytest.raises(EmbeddingError) as exc:
        _client(fake).embed_query("x")
    assert "network down" in str(exc.value)


def test_文档向量化失败时包装为EmbeddingError():
    fake = FakeEmbeddings(error=RuntimeError("timeout"))
    with pytest.raises(EmbeddingError):
        _client(fake).embed_documents(["x"])


def test_未配置时from_settings抛出EmbeddingError():
    settings = Settings(embedding_api_key="", embedding_model_name="")
    assert settings.embedding_configured is False
    with pytest.raises(EmbeddingError):
        EmbeddingClient.from_settings(settings)


def test_配置api_key与model后embedding_configured为真():
    settings = Settings(embedding_api_key="sk-x", embedding_model_name="text-embedding-v4")
    assert settings.embedding_configured is True
