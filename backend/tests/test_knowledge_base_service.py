"""app/services/knowledge_base_service.py 单测：导入、列出、删除及权限。

mock 说明：
- get_embedding_client / get_kb_milvus_client 用替身替换——不触达真实 embedding / Milvus。
- get_settings 用伪 settings——控制 kb_configured、切分参数与维度。
- split_text 用真实实现（纯函数、无外部依赖）。
"""
import pytest

import app.services.knowledge_base_service as svc
from app.llm import EmbeddingError


class FakeEmbedding:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def embed_documents(self, texts):
        if self.error:
            raise self.error
        self.calls.append(list(texts))
        return [[float(i)] for i, _ in enumerate(texts)]


class FakeStore:
    def __init__(self, exists=True, rows=None):
        self._exists = exists
        self._rows = rows if rows is not None else []
        self.ensured = []
        self.upserted = []
        self.queries = []
        self.deletes = []

    def ensure_collection(self, dim):
        self.ensured.append(dim)

    def upsert(self, data):
        self.upserted.append(data)
        return {"upsert_count": len(data)}

    def collection_exists(self):
        return self._exists

    def query(self, expr, output_fields, limit=1000):
        self.queries.append(expr)
        return self._rows

    def delete(self, expr):
        self.deletes.append(expr)
        return {"delete_count": len(self._rows)}


def _fake_settings(configured=True, chunk=100, overlap=10, dim=1024, oss=False):
    return type(
        "S",
        (),
        {
            "kb_configured": configured,
            "kb_chunk_size": chunk,
            "kb_chunk_overlap": overlap,
            "milvus_dim": dim,
            "oss_configured": oss,
            "vl_configured": False,
        },
    )()


@pytest.fixture
def patch(monkeypatch):
    def _apply(configured=True, embed_error=None, store=None, dim=1024, oss=False):
        emb = FakeEmbedding(error=embed_error)
        store = store or FakeStore()
        monkeypatch.setattr(
            svc, "get_settings", lambda: _fake_settings(configured, dim=dim, oss=oss)
        )
        monkeypatch.setattr(svc, "get_embedding_client", lambda: emb)
        monkeypatch.setattr(svc, "get_kb_milvus_client", lambda: store)
        return emb, store

    return _apply


# ---------- 导入 ----------

def test_导入文档写入scope与owner_id等字段(patch):
    emb, store = patch()
    result = svc.import_document("kb.md", ("句子。" * 100).encode("utf-8"), "global", 7)
    assert result["scope"] == "global" and result["filename"] == "kb.md"
    assert result["chunks"] == len(store.upserted[0])
    first = store.upserted[0][0]
    assert first["scope"] == "global" and first["owner_id"] == 7
    assert first["doc_id"] == result["doc_id"] and first["chunk_index"] == 0


def test_未配置维度时按embedding输出维度建集合(patch):
    # milvus_dim=0 → 不应把 0 传给 Milvus，而是用实际向量长度（FakeEmbedding 返回 1 维）
    _, store = patch(dim=0)
    svc.import_document("kb.md", ("句子。" * 100).encode("utf-8"), "personal", 1)
    assert store.ensured == [1]


def test_非法scope报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.import_document("x.txt", b"content", "team", 1)


def test_未配置知识库时导入报错(patch):
    patch(configured=False)
    with pytest.raises(svc.KnowledgeBaseError):
        svc.import_document("x.txt", b"content", "personal", 1)


def test_非utf8文本报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.import_document("x.txt", b"\xff\xfe\x00\x01", "personal", 1)


def test_不支持的格式报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.import_document("legacy.doc", b"whatever", "personal", 1)


def test_图片块转存oss并ocr后入库(patch, monkeypatch):
    from app.services.document_parsing import ImageBlock, TextBlock

    _, store = patch(oss=True)
    monkeypatch.setattr(
        svc,
        "parse_document",
        lambda fn, raw, vl_extract=None: [TextBlock("正文段落"), ImageBlock(b"imgbytes", "png")],
    )

    class FakeOss:
        def upload_bytes(self, key, data, content_type=None):
            return f"https://cdn/{key}"

    monkeypatch.setattr(svc, "get_oss_client", lambda: FakeOss())
    monkeypatch.setattr(svc, "ocr_image", lambda data: "图中识别出的文字")

    result = svc.import_document("with_image.pdf", b"...", "personal", 3)
    records = store.upserted[0]
    image_rec = next(r for r in records if r["kind"] == "image")
    assert image_rec["image_url"].startswith("https://cdn/kb/")
    assert "地址:" in image_rec["text"] and "图中识别出的文字" in image_rec["text"]
    assert any(r["kind"] == "text" for r in records)
    assert result["chunks"] == len(records)


# ---------- 预览 / 提交 / 查看分片 ----------

_DOC_ID = "a" * 32  # 合法 doc_id（32 位十六进制）


def test_预览返回chunk列表且不写库(patch):
    _, store = patch()
    result = svc.preview_document("kb.md", ("句子。" * 100).encode("utf-8"), "personal")
    assert result["filename"] == "kb.md" and result["scope"] == "personal"
    assert len(result["chunks"]) >= 1
    assert result["chunks"][0]["index"] == 0 and "text" in result["chunks"][0]
    assert store.upserted == []  # 预览不写入 Milvus


def test_预览空文档报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.preview_document("empty.txt", b"   \n ", "personal")


def test_提交编辑后的chunk写入并删旧(patch):
    _, store = patch()
    chunks = [{"text": "编辑后的片段一", "kind": "text"}, {"text": "片段二"}]
    result = svc.commit_chunks(_DOC_ID, "kb.md", "global", 7, chunks)
    assert result["chunks"] == 2
    assert store.deletes == [f'doc_id == "{_DOC_ID}"']  # 先删旧分片
    recs = store.upserted[0]
    assert [r["text"] for r in recs] == ["编辑后的片段一", "片段二"]
    assert recs[0]["scope"] == "global" and recs[0]["owner_id"] == 7


def test_提交时丢弃空白chunk(patch):
    _, store = patch()
    chunks = [{"text": "有内容"}, {"text": "   "}, {"text": ""}]
    result = svc.commit_chunks(_DOC_ID, "kb.md", "personal", 1, chunks)
    assert result["chunks"] == 1 and len(store.upserted[0]) == 1


def test_提交全空chunk报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.commit_chunks(_DOC_ID, "kb.md", "personal", 1, [{"text": "  "}])


def test_提交非法doc_id报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.commit_chunks("not-a-valid-id", "kb.md", "personal", 1, [{"text": "x"}])


def test_覆盖他人文档被拒(patch):
    store = FakeStore(rows=[{"owner_id": 99}])
    patch(store=store)
    with pytest.raises(svc.PermissionDeniedError):
        svc.commit_chunks(_DOC_ID, "kb.md", "personal", 7, [{"text": "x"}])
    assert store.upserted == []  # 未写入


def test_查看分片按序返回(patch):
    rows = [
        {"chunk_index": 1, "text": "B", "kind": "text", "image_url": "", "owner_id": 7, "scope": "personal"},
        {"chunk_index": 0, "text": "A", "kind": "text", "image_url": "", "owner_id": 7, "scope": "personal"},
    ]
    patch(store=FakeStore(rows=rows))
    chunks = svc.get_document_chunks(_DOC_ID, owner_id=7)
    assert [c["text"] for c in chunks] == ["A", "B"]  # 按 chunk_index 排序


def test_查看不存在文档报404(patch):
    patch(store=FakeStore(rows=[]))
    with pytest.raises(svc.DocumentNotFoundError):
        svc.get_document_chunks(_DOC_ID, owner_id=7)


def test_查看他人personal文档被拒(patch):
    rows = [{"chunk_index": 0, "text": "x", "owner_id": 99, "scope": "personal"}]
    patch(store=FakeStore(rows=rows))
    with pytest.raises(svc.PermissionDeniedError):
        svc.get_document_chunks(_DOC_ID, owner_id=7)


def test_图片无oss且ocr为空则跳过(patch, monkeypatch):
    from app.services.document_parsing import ImageBlock

    _, store = patch(oss=False)  # 未配置 OSS
    monkeypatch.setattr(
        svc, "parse_document", lambda fn, raw, vl_extract=None: [ImageBlock(b"x", "png")]
    )
    monkeypatch.setattr(svc, "ocr_image", lambda data: "")  # OCR 无结果
    # 既无链接也无文字 → 该图片无可索引内容 → 整篇无段落 → 报空
    with pytest.raises(svc.KnowledgeBaseError):
        svc.import_document("img_only.docx", b"...", "personal", 1)


def test_空文档报错(patch):
    patch()
    with pytest.raises(svc.KnowledgeBaseError):
        svc.import_document("empty.txt", b"   \n  ", "personal", 1)


def test_向量化失败转为知识库错误(patch):
    patch(embed_error=EmbeddingError("embedding down"))
    with pytest.raises(svc.KnowledgeBaseError) as exc:
        svc.import_document("x.txt", b"some real content here", "personal", 1)
    assert "embedding down" in str(exc.value)


# ---------- 列出 ----------

def test_列出按文档聚合并统计片数(patch):
    rows = [
        {"doc_id": "a", "filename": "g.md", "scope": "global", "owner_id": 2},
        {"doc_id": "a", "filename": "g.md", "scope": "global", "owner_id": 2},
        {"doc_id": "b", "filename": "p.md", "scope": "personal", "owner_id": 7},
    ]
    patch(store=FakeStore(rows=rows))
    docs = svc.list_documents(owner_id=7)
    by_id = {d["doc_id"]: d for d in docs}
    assert by_id["a"]["chunks"] == 2 and by_id["a"]["scope"] == "global"
    assert by_id["b"]["chunks"] == 1 and by_id["b"]["owner_id"] == 7


def test_列出过滤条件包含全局或本人(patch):
    store = FakeStore(rows=[])
    patch(store=store)
    svc.list_documents(owner_id=42)
    assert store.queries == ['scope == "global" or owner_id == 42']


def test_未配置或集合不存在时列出返回空(patch):
    patch(configured=False)
    assert svc.list_documents(owner_id=1) == []
    patch(store=FakeStore(exists=False))
    assert svc.list_documents(owner_id=1) == []


# ---------- 删除 ----------

VALID_DOC_ID = "a" * 32  # 32 位十六进制，符合 uuid4().hex


def test_本人可删除自己的文档(patch):
    store = FakeStore(rows=[{"owner_id": 7}, {"owner_id": 7}])
    patch(store=store)
    deleted = svc.delete_document(VALID_DOC_ID, owner_id=7)
    assert deleted == 2
    assert store.deletes == [f'doc_id == "{VALID_DOC_ID}"']


def test_删除他人文档被拒(patch):
    store = FakeStore(rows=[{"owner_id": 99}])
    patch(store=store)
    with pytest.raises(svc.PermissionDeniedError):
        svc.delete_document(VALID_DOC_ID, owner_id=7)
    assert store.deletes == []  # 未执行删除


def test_删除不存在的文档报404错误(patch):
    patch(store=FakeStore(rows=[]))
    with pytest.raises(svc.DocumentNotFoundError):
        svc.delete_document(VALID_DOC_ID, owner_id=7)


def test_非法doc_id视为不存在且不查询(patch):
    store = FakeStore()
    patch(store=store)
    with pytest.raises(svc.DocumentNotFoundError):
        svc.delete_document("'; drop --", owner_id=7)
    assert store.queries == []  # 非法 id 直接拒绝，避免过滤表达式注入


def test_chunk_id稳定可重导():
    assert svc._chunk_id("doc-abc", 3) == svc._chunk_id("doc-abc", 3)
    assert svc._chunk_id("doc-abc", 3) != svc._chunk_id("doc-abc", 4)
