"""app/services/rag_service.py 单测：范围过滤、召回、上下文拼接与降级。

mock 说明：
- get_embedding_client / get_kb_milvus_client 用替身替换——不触达真实 embedding / Milvus。
- get_settings 用伪 settings——控制 kb_configured 与 rag_top_k。
"""
import pytest

import app.services.rag_service as rag


class FakeEmbedding:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeStore:
    def __init__(self, exists=True, hits=None, error=None):
        self._exists = exists
        self._hits = hits if hits is not None else []
        self.error = error
        self.search_calls = []

    def collection_exists(self):
        return self._exists

    def search(self, vector, limit, output_fields, expr):
        if self.error:
            raise self.error
        self.search_calls.append((vector, limit, output_fields, expr))
        return self._hits


def _fake_settings(configured=True, top_k=4, rerank=False, recall_k=20):
    return type(
        "S",
        (),
        {
            "kb_configured": configured,
            "rag_top_k": top_k,
            "rerank_configured": rerank,
            "rag_recall_k": recall_k,
            "embedding_configured": True,
        },
    )()


@pytest.fixture
def patch(monkeypatch):
    def _apply(configured=True, top_k=4, store=None, rerank=False, recall_k=20):
        store = store or FakeStore()
        monkeypatch.setattr(
            rag, "get_settings", lambda: _fake_settings(configured, top_k, rerank, recall_k)
        )
        monkeypatch.setattr(rag, "get_embedding_client", lambda: FakeEmbedding())
        monkeypatch.setattr(rag, "get_kb_milvus_client", lambda: store)
        return store

    return _apply


# ---------- 范围过滤 ----------

def test_scope过滤表达式按范围与用户生成():
    assert rag._scope_filter("global", 7) == 'scope == "global"'
    assert rag._scope_filter("personal", 7) == 'owner_id == 7 and scope == "personal"'
    assert rag._scope_filter("both", 7) == 'scope == "global" or owner_id == 7'


def test_游客范围退化():
    assert rag._scope_filter("both", None) == 'scope == "global"'  # both 退化为仅全局
    assert rag._scope_filter("personal", None) is None  # 游客无个人库
    assert rag._scope_filter("none", 7) is None  # 关闭检索


# ---------- 召回 ----------

def test_召回时带top_k与范围过滤并规整字段(patch):
    hits = [{"entity": {"text": "片段A", "filename": "g.md", "scope": "global"}, "distance": 0.9}]
    store = patch(top_k=3, store=FakeStore(hits=hits))
    passages = rag.retrieve_context("问题", user_id=7, scope="both")
    assert passages == [{"text": "片段A", "filename": "g.md", "scope": "global"}]
    _, limit, fields, expr = store.search_calls[0]
    assert limit == 3 and expr == 'scope == "global" or owner_id == 7'


def test_启用rerank时多召回再重排取前top_k(patch, monkeypatch):
    hits = [{"entity": {"text": f"片段{i}", "filename": "f", "scope": "global"}} for i in range(4)]
    store = patch(top_k=2, rerank=True, recall_k=10, store=FakeStore(hits=hits))
    # rerank 把候选倒序并取前 top_n
    monkeypatch.setattr(rag, "rerank", lambda q, docs, top_n: [3, 2, 1, 0][:top_n])
    passages = rag.retrieve_context("问题", user_id=7, scope="both")
    _, limit, _, _ = store.search_calls[0]
    assert limit == 10  # 启用 rerank → 用 recall_k 粗召回
    assert [p["text"] for p in passages] == ["片段3", "片段2"]  # 重排后取前 2


def test_关闭范围时不检索(patch):
    store = patch()
    assert rag.retrieve_context("问题", user_id=7, scope="none") == []
    assert store.search_calls == []


def test_未配置知识库时返回空(patch):
    store = patch(configured=False)
    assert rag.retrieve_context("问题", user_id=7, scope="both") == []
    assert store.search_calls == []


def test_空问题返回空(patch):
    store = patch()
    assert rag.retrieve_context("   ", user_id=7, scope="both") == []
    assert store.search_calls == []


def test_集合不存在时返回空(patch):
    patch(store=FakeStore(exists=False))
    assert rag.retrieve_context("问题", user_id=7, scope="both") == []


def test_检索异常时降级为空不抛出(patch):
    patch(store=FakeStore(error=RuntimeError("milvus down")))
    assert rag.retrieve_context("问题", user_id=7, scope="both") == []


# ---------- 预热 ----------

def test_预热调用embedding与rerank(patch, monkeypatch):
    patch(rerank=True)  # rerank_configured=True，embedding_configured 在 _fake_settings 中为 True
    calls = {"embed": 0, "rerank": 0}

    class _Emb:
        def embed_query(self, text):
            calls["embed"] += 1
            return [0.1]

    monkeypatch.setattr(rag, "get_embedding_client", lambda: _Emb())
    monkeypatch.setattr(rag, "rerank", lambda q, docs, top_n: calls.update(rerank=calls["rerank"] + 1))
    rag.warmup()
    assert calls["embed"] == 1 and calls["rerank"] == 1


def test_预热失败被静默吞掉不抛出(patch, monkeypatch):
    patch()  # rerank 关闭，仅预热 embedding

    class _Emb:
        def embed_query(self, text):
            raise RuntimeError("cold start timeout")

    monkeypatch.setattr(rag, "get_embedding_client", lambda: _Emb())
    rag.warmup()  # 不应抛出


# ---------- 知识库检索工具（function calling） ----------

def test_构造知识库工具_未配置或范围不可检索时返回None(patch):
    patch(configured=False)
    assert rag.make_kb_search_tool(7, "both") is None
    patch(configured=True)
    assert rag.make_kb_search_tool(7, "none") is None  # 关闭检索
    assert rag.make_kb_search_tool(None, "personal") is None  # 游客无个人库


def test_构造的知识库工具检索并格式化命中(patch, monkeypatch):
    patch(configured=True)
    monkeypatch.setattr(rag, "retrieve_context", lambda q, u, s: [{"text": "片段A", "filename": "a.md"}])
    tool = rag.make_kb_search_tool(7, "both")
    assert tool.name == "search_knowledge_base"
    result = tool.invoke({"query": "问题"})
    assert "片段A" in result and "a.md" in result


def test_构造的知识库工具无命中时返回提示(patch, monkeypatch):
    patch(configured=True)
    monkeypatch.setattr(rag, "retrieve_context", lambda q, u, s: [])
    tool = rag.make_kb_search_tool(7, "global")
    assert "未找到" in tool.invoke({"query": "x"})


# ---------- 上下文拼接 ----------

def test_拼接上下文块包含来源与编号():
    block = rag.build_context_block(
        [{"text": "内容1", "filename": "a.md"}, {"text": "内容2", "filename": ""}]
    )
    assert "[1]" in block and "a.md" in block and "内容1" in block
    assert "[2]" in block and "知识库" in block  # filename 为空时回退“知识库”


def test_无有效片段时上下文块为None():
    assert rag.build_context_block([]) is None
    assert rag.build_context_block([{"text": "   ", "filename": "a"}]) is None
