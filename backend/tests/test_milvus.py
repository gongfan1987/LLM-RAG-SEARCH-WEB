"""app/utils/milvus.py 单测：集合管理、插入、检索、错误包装与配置校验。

mock 说明：
- 用 FakeSdkClient 替身注入 MilvusStore，不创建真实 pymilvus 连接、不连 Milvus、不发网络请求。
- settings 用 monkeypatch 设置，不依赖真实 .env。
"""
import pytest

from app.core.config import Settings
from app.utils.milvus import MilvusError, MilvusStore


class FakeSdkClient:
    """记录调用参数的伪 pymilvus 客户端；可设置 has / error 模拟不同场景。"""

    def __init__(self, has=False, error: Exception | None = None, search_result=None, query_rows=None):
        self._has = has
        self.error = error
        self.search_result = search_result if search_result is not None else [[{"id": 1}]]
        self.query_rows = query_rows if query_rows is not None else [{"id": 1}]
        self.created = []
        self.loaded = []
        self.released = []
        self.inserted = []
        self.upserted = []
        self.search_calls = []
        self.query_exprs = []
        self.delete_exprs = []

    def has_collection(self, name):
        return self._has

    def create_collection(self, collection_name, dimension):
        self.created.append((collection_name, dimension))

    def load_collection(self, collection_name, replica_number=1):
        self.loaded.append((collection_name, replica_number))

    def release_collection(self, collection_name):
        self.released.append(collection_name)

    def insert(self, collection_name, data):
        if self.error:
            raise self.error
        self.inserted.append((collection_name, data))
        return {"insert_count": len(data)}

    def upsert(self, collection_name, data):
        if self.error:
            raise self.error
        self.upserted.append((collection_name, data))
        return {"upsert_count": len(data)}

    def query(self, collection_name, filter, output_fields, limit):
        if self.error:
            raise self.error
        self.query_exprs.append((collection_name, filter, output_fields, limit))
        return self.query_rows

    def delete(self, collection_name, filter):
        if self.error:
            raise self.error
        self.delete_exprs.append((collection_name, filter))
        return {"delete_count": 1}

    def search(self, collection_name, data, limit, output_fields=None, filter=""):
        if self.error:
            raise self.error
        self.search_calls.append((collection_name, data, limit, output_fields, filter))
        return self.search_result


def _store(client):
    return MilvusStore(uri="http://x", token="", collection="docs", _client=client)


def test_集合不存在时按维度创建():
    client = FakeSdkClient(has=False)
    _store(client).ensure_collection(dim=1024)
    assert client.created == [("docs", 1024)]


def test_集合已存在时不重复创建():
    client = FakeSdkClient(has=True)
    _store(client).ensure_collection(dim=1024)
    assert client.created == []


def test_插入透传集合名与数据并返回结果():
    client = FakeSdkClient()
    data = [{"id": 1, "vector": [0.1, 0.2]}]
    result = _store(client).insert(data)
    assert client.inserted == [("docs", data)]
    assert result == {"insert_count": 1}


def test_upsert按主键覆盖透传集合名与数据():
    client = FakeSdkClient()
    data = [{"id": 1, "vector": [0.1]}]
    result = _store(client).upsert(data)
    assert client.upserted == [("docs", data)]
    assert result == {"upsert_count": 1}


def test_检索展开为单个查询的命中列表():
    client = FakeSdkClient(search_result=[[{"id": 7, "distance": 0.9}]])
    hits = _store(client).search([0.1, 0.2], limit=3, output_fields=["text"], expr='scope == "global"')
    assert hits == [{"id": 7, "distance": 0.9}]
    assert client.search_calls == [("docs", [[0.1, 0.2]], 3, ["text"], 'scope == "global"')]


def test_检索无结果时返回空列表():
    client = FakeSdkClient(search_result=[])
    assert _store(client).search([0.1]) == []


def test_query按表达式过滤并透传参数():
    client = FakeSdkClient(query_rows=[{"doc_id": "a"}])
    rows = _store(client).query(expr='scope == "global"', output_fields=["doc_id"], limit=50)
    assert rows == [{"doc_id": "a"}]
    assert client.query_exprs == [("docs", 'scope == "global"', ["doc_id"], 50)]


def test_delete按表达式删除并透传集合名():
    client = FakeSdkClient()
    _store(client).delete(expr='doc_id == "abc"')
    assert client.delete_exprs == [("docs", 'doc_id == "abc"')]


def test_collection_exists透传has_collection结果():
    assert _store(FakeSdkClient(has=True)).collection_exists() is True
    assert _store(FakeSdkClient(has=False)).collection_exists() is False


def test_插入失败时包装为MilvusError():
    client = FakeSdkClient(error=RuntimeError("conn refused"))
    with pytest.raises(MilvusError) as exc:
        _store(client).insert([{"id": 1, "vector": [0.1]}])
    assert "conn refused" in str(exc.value)


def test_检索失败时包装为MilvusError():
    client = FakeSdkClient(error=RuntimeError("timeout"))
    with pytest.raises(MilvusError):
        _store(client).search([0.1])


def test_未配置milvus时from_settings抛出MilvusError():
    settings = Settings(milvus_uri="", milvus_collection="")
    assert settings.milvus_configured is False
    with pytest.raises(MilvusError):
        MilvusStore.from_settings(settings)


def test_uri与collection都填时milvus_configured为真():
    settings = Settings(milvus_uri="http://127.0.0.1:19530", milvus_collection="docs")
    assert settings.milvus_configured is True
