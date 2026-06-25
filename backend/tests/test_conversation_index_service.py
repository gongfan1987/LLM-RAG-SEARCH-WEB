"""app/services/conversation_index_service.py 单测：对话消息向量化并写入 Milvus。

mock 说明：
- get_embedding_client / get_milvus_client 用替身替换——不触达真实 embedding / Milvus、不发网络。
- get_settings 用伪 settings——精确控制 embedding_configured / milvus_configured 开关与维度。
- 每个用例前重置模块级 _collection_ready，避免相互污染。
"""
import pytest

import app.services.conversation_index_service as svc


class FakeEmbedding:
    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [[float(i)] for i, _ in enumerate(texts)]


class FakeStore:
    def __init__(self, fail=False):
        self.fail = fail
        self.ensured = []
        self.inserted = []

    def ensure_collection(self, dim):
        self.ensured.append(dim)

    def insert(self, data):
        if self.fail:
            raise RuntimeError("milvus down")
        self.inserted.append(data)
        return {"insert_count": len(data)}


def _fake_settings(embedding=True, milvus=True, dim=1024):
    return type(
        "S", (), {"embedding_configured": embedding, "milvus_configured": milvus, "milvus_dim": dim}
    )()


@pytest.fixture(autouse=True)
def reset_ready():
    svc._collection_ready = False
    yield
    svc._collection_ready = False


@pytest.fixture
def patch(monkeypatch):
    def _apply(embedding=True, milvus=True, dim=1024, store_fail=False):
        emb, store = FakeEmbedding(), FakeStore(fail=store_fail)
        monkeypatch.setattr(svc, "get_settings", lambda: _fake_settings(embedding, milvus, dim))
        monkeypatch.setattr(svc, "get_embedding_client", lambda: emb)
        monkeypatch.setattr(svc, "get_milvus_client", lambda: store)
        return emb, store

    return _apply


def test_配置齐全时向量化并写入milvus带完整字段(patch):
    emb, store = patch(dim=1024)
    items = [
        {"id": 1, "session_id": 9, "role": "user", "text": "今天几号"},
        {"id": 2, "session_id": 9, "role": "assistant", "text": "6 月 23 日"},
    ]
    n = svc.index_messages(items)
    assert n == 2
    assert emb.calls == [["今天几号", "6 月 23 日"]]
    assert store.ensured == [1024]
    assert store.inserted[0][0] == {
        "id": 1, "vector": [0.0], "text": "今天几号", "role": "user", "session_id": 9,
    }


def test_未配置维度时按embedding输出维度建集合(patch):
    _, store = patch(dim=0)  # FakeEmbedding 返回 1 维向量
    svc.index_messages([{"id": 1, "session_id": 9, "role": "user", "text": "a"}])
    assert store.ensured == [1]


def test_embedding未配置时整体no_op(patch):
    emb, store = patch(embedding=False)
    assert svc.index_messages([{"id": 1, "session_id": 9, "role": "user", "text": "x"}]) == 0
    assert emb.calls == [] and store.inserted == []


def test_milvus未配置时整体no_op(patch):
    emb, store = patch(milvus=False)
    assert svc.index_messages([{"id": 1, "session_id": 9, "role": "user", "text": "x"}]) == 0
    assert emb.calls == [] and store.inserted == []


def test_空文本被过滤不触发向量化(patch):
    emb, store = patch()
    assert svc.index_messages([{"id": 1, "session_id": 9, "role": "assistant", "text": ""}]) == 0
    assert emb.calls == []


def test_集合在进程内只建一次(patch):
    _, store = patch()
    item = [{"id": 1, "session_id": 9, "role": "user", "text": "a"}]
    svc.index_messages(item)
    svc.index_messages(item)
    assert store.ensured == [1024]  # 第二次不再 ensure


def test_写入失败时降级返回0且不抛出(patch):
    patch(store_fail=True)
    assert svc.index_messages([{"id": 1, "session_id": 9, "role": "user", "text": "x"}]) == 0
