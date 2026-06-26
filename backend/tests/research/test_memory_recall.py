"""app/research/memory/recall.py 单测：轨迹向量化入库与语义召回，含降级路径。

mock：get_embedding_client / get_trajectory_milvus_client / get_settings 全部替身，不触达真实服务。
"""
import pytest

import app.research.memory.recall as recall
from app.core.config import Settings
from app.utils.milvus import get_trajectory_milvus_client


class FakeEmbedding:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeStore:
    def __init__(self, fail=False, hits=None):
        self.fail = fail
        self._hits = hits or []
        self.inserted = []

    def ensure_collection(self, dim):
        pass

    def insert(self, data):
        if self.fail:
            raise RuntimeError("milvus down")
        self.inserted.append(data)

    def search(self, vector, limit, output_fields, expr):
        if self.fail:
            raise RuntimeError("milvus down")
        return self._hits


def _settings(milvus=True, embedding=True, dim=3):
    return type("S", (), {
        "milvus_configured": milvus, "embedding_configured": embedding, "milvus_dim": dim,
    })()


@pytest.fixture(autouse=True)
def reset_ready():
    recall._collection_ready = False
    yield
    recall._collection_ready = False


def test_未配置milvus召回返回空(monkeypatch):
    monkeypatch.setattr(recall, "get_settings", lambda: _settings(milvus=False))
    assert recall.related_trajectories("新能源", user_id=1) == []


def test_召回命中返回主题与摘要(monkeypatch):
    store = FakeStore(hits=[{"entity": {"topic": "光伏", "summary": "光伏摘要"}}])
    monkeypatch.setattr(recall, "get_settings", lambda: _settings())
    monkeypatch.setattr(recall, "get_embedding_client", lambda: FakeEmbedding())
    monkeypatch.setattr(recall, "get_trajectory_milvus_client", lambda: store)
    out = recall.related_trajectories("新能源", user_id=1)
    assert out == [{"topic": "光伏", "summary": "光伏摘要"}]


def test_milvus失败召回降级为空不抛错(monkeypatch):
    store = FakeStore(fail=True)
    monkeypatch.setattr(recall, "get_settings", lambda: _settings())
    monkeypatch.setattr(recall, "get_embedding_client", lambda: FakeEmbedding())
    monkeypatch.setattr(recall, "get_trajectory_milvus_client", lambda: store)
    assert recall.related_trajectories("新能源", user_id=1) == []


def test_入库失败静默不抛错(monkeypatch):
    store = FakeStore(fail=True)
    monkeypatch.setattr(recall, "get_settings", lambda: _settings())
    monkeypatch.setattr(recall, "get_embedding_client", lambda: FakeEmbedding())
    monkeypatch.setattr(recall, "get_trajectory_milvus_client", lambda: store)
    recall.index_trajectory(1, user_id=1, topic="t", summary="s")  # 不抛异常即通过


def test_轨迹召回绑定独立集合而非对话索引集合(monkeypatch):
    """回归测试：get_trajectory_milvus_client 必须绑定 milvus_trajectory_collection，
    而非 milvus_collection（对话索引集合），否则轨迹向量会污染对话索引数据。
    """
    import app.utils.milvus as milvus_module

    get_trajectory_milvus_client.cache_clear()
    settings = Settings(
        milvus_uri="http://127.0.0.1:19530",
        milvus_collection="conv",
        milvus_trajectory_collection="task_trajectory",
    )
    monkeypatch.setattr(milvus_module, "get_settings", lambda: settings)

    captured = {}
    real_store_cls = milvus_module.MilvusStore

    def fake_store(uri, token, collection, **kwargs):
        captured["collection"] = collection
        return object.__new__(real_store_cls)

    monkeypatch.setattr(milvus_module, "MilvusStore", fake_store)
    get_trajectory_milvus_client()

    assert captured["collection"] == "task_trajectory"
    assert captured["collection"] != settings.milvus_collection
    get_trajectory_milvus_client.cache_clear()
