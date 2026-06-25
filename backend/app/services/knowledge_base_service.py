"""知识库文档导入与管理：导入（上传→解析→切分→embedding→Milvus）、列出、删除。

编排技术组件：document_parsing（多格式解析）、split_text（切分）、ocr_image（图片转文字）、
OssClient（图片转存）、EmbeddingClient（向量化）、MilvusStore（KB 集合）。

支持格式：.txt / .md / .pdf / .docx / .xlsx（.doc/.xls 暂不支持）。表格序列化为 markdown 文本；
图片提取后上传 OSS 并 OCR，生成「含图片链接 + 图中文字」的文本块入库。

可见性与权限（无管理员角色，规则力求简单且安全）：
- 每个文档记录上传者 owner_id；scope ∈ {global, personal} 只控制「可见性」。
- 列出：全部 global 文档 + 自己的 personal 文档。
- 删除：仅上传者本人可删（owner-only），无论 global 还是 personal。

与「对话自动索引」的关键差异：本流程是**用户主动发起**且有返回结果，失败要显式报错
（抛 KnowledgeBaseError 及其子类，由路由转 HTTP 4xx），不像旁路索引那样静默降级。
"""
import hashlib
import re
from uuid import uuid4

from app.core.config import get_settings
from app.llm import EmbeddingError, get_embedding_client
from app.services.document_parsing import (
    ImageBlock,
    TextBlock,
    UnsupportedFormatError,
    parse_document,
)
from app.utils.milvus import MilvusError, get_kb_milvus_client
from app.utils.ocr import ocr_image
from app.utils.oss import OssError, get_oss_client
from app.utils.text import split_markdown

_VALID_SCOPES = ("global", "personal")
_DOC_ID_RE = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex；同时防止过滤表达式注入
_QUERY_LIMIT = 16384  # 列出/删除时单次查询的最大命中行数（足够覆盖中小规模知识库）


class KnowledgeBaseError(Exception):
    """知识库操作失败的统一异常，由路由转换为 HTTP 错误响应。"""


class DocumentNotFoundError(KnowledgeBaseError):
    """目标文档不存在（路由转 404）。"""


class PermissionDeniedError(KnowledgeBaseError):
    """无权操作该文档（路由转 403）。"""


def _chunk_id(doc_id: str, index: int) -> int:
    """由 doc_id + chunk 序号生成稳定的 int64 主键，便于同文档重导时 upsert 覆盖。"""
    digest = hashlib.sha256(f"{doc_id}:{index}".encode()).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def _ingest_image(block: ImageBlock, doc_id: str, index: int) -> dict | None:
    """处理一张图片：上传 OSS（取链接）+ OCR（取文字），合成一个文本段。

    OSS 未配置或上传失败 → 无链接；OCR 不可用或失败 → 无文字（均降级）。
    两者都没有则返回 None（无可索引信息，跳过）。
    """
    settings = get_settings()
    image_url = ""
    if settings.oss_configured:
        try:
            key = f"kb/{doc_id}/img_{index}.{block.ext}"
            image_url = get_oss_client().upload_bytes(
                key, block.data, content_type=f"image/{block.ext}"
            )
        except OssError:
            image_url = ""

    ocr_text = ocr_image(block.data)

    if not image_url and not ocr_text:
        return None
    parts = ["[图片]"]
    if image_url:
        parts.append(f"地址: {image_url}")
    if ocr_text:
        parts.append(f"图中文字: {ocr_text}")
    return {"text": "\n".join(parts), "kind": "image", "image_url": image_url}


def _build_segments(blocks: list, doc_id: str, chunk_size: int, overlap: int) -> list[dict]:
    """把解析出的内容块转成待向量化的文本段：文本/表格按 split_text 切分，图片转存+OCR。"""
    segments: list[dict] = []
    image_index = 0
    for block in blocks:
        if isinstance(block, TextBlock):
            # 结构感知切分：markdown 表格整体保留、不被切碎（PDF/Word/Excel 的表都转成了 markdown）。
            for chunk in split_markdown(block.text, chunk_size, overlap):
                segments.append({"text": chunk, "kind": "text", "image_url": ""})
        elif isinstance(block, ImageBlock):
            seg = _ingest_image(block, doc_id, image_index)
            image_index += 1
            if seg:
                segments.append(seg)
    return segments


def _require_kb(scope: str | None = None) -> None:
    """统一前置校验：scope 合法 + 知识库已配置。"""
    if scope is not None and scope not in _VALID_SCOPES:
        raise KnowledgeBaseError("scope 仅支持 global 或 personal")
    if not get_settings().kb_configured:
        raise KnowledgeBaseError(
            "知识库未启用：请配置 EMBEDDING_* 与 MILVUS_URI / MILVUS_KB_COLLECTION"
        )


def _embed_and_upsert(
    doc_id: str, filename: str, scope: str, owner_id: int, segments: list[dict]
) -> int:
    """把 segments 向量化并写入 Milvus；按 doc_id 先删旧分片再写，保证重导/编辑覆盖幂等。"""
    settings = get_settings()
    try:
        vectors = get_embedding_client().embed_documents([s["text"] for s in segments])
        store = get_kb_milvus_client()
        # 集合维度优先用配置（MILVUS_DIM），未配置（0）时按实际 embedding 输出维度推导。
        store.ensure_collection(settings.milvus_dim or len(vectors[0]))
        store.delete(expr=f'doc_id == "{doc_id}"')  # 幂等：清掉该文档旧分片（新 doc 则无操作）
        data = [
            {
                "id": _chunk_id(doc_id, i),
                "vector": vec,
                "text": seg["text"],
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": i,
                "scope": scope,
                "owner_id": owner_id,
                "kind": seg.get("kind", "text"),
                "image_url": seg.get("image_url", ""),
            }
            for i, (seg, vec) in enumerate(zip(segments, vectors))
        ]
        store.upsert(data)
    except (EmbeddingError, MilvusError) as exc:
        raise KnowledgeBaseError(f"文档导入失败: {exc}") from exc
    return len(segments)


def preview_document(filename: str, raw: bytes, scope: str) -> dict:
    """解析并切分文档，返回可供预览/编辑的 chunk 列表，**不写入 Milvus**。

    生成 doc_id（图片即在此阶段转存 OSS + OCR，所见即所存）；调用方编辑后再走 commit_chunks。
    """
    _require_kb(scope)
    # PDF 且开启了 VL 时，注入「图片→markdown」回调，用多模态模型还原复杂表格；否则纯文本提取。
    vl_extract = None
    if filename.lower().endswith(".pdf") and get_settings().vl_configured:
        from app.llm import image_to_markdown

        vl_extract = image_to_markdown
    try:
        blocks = parse_document(filename, raw, vl_extract=vl_extract)
    except UnsupportedFormatError as exc:
        raise KnowledgeBaseError(str(exc)) from exc

    settings = get_settings()
    doc_id = uuid4().hex
    segments = _build_segments(blocks, doc_id, settings.kb_chunk_size, settings.kb_chunk_overlap)
    if not segments:
        raise KnowledgeBaseError("文档内容为空，无可索引内容")
    return {
        "doc_id": doc_id,
        "filename": filename,
        "scope": scope,
        "chunks": [
            {"index": i, "text": s["text"], "kind": s["kind"], "image_url": s["image_url"]}
            for i, s in enumerate(segments)
        ],
    }


def commit_chunks(
    doc_id: str, filename: str, scope: str, owner_id: int, chunks: list[dict]
) -> dict:
    """把（可能已编辑的）chunk 列表向量化并写入 Milvus。

    用于「预览后确认导入」与「已入库文档编辑后覆盖」两种场景。覆盖已有文档时校验归属
    （仅上传者可改）；空白 chunk 会被丢弃；按 doc_id 删旧写新，保证幂等。
    """
    _require_kb(scope)
    if not _DOC_ID_RE.match(doc_id):
        raise KnowledgeBaseError("无效的 doc_id")
    segments = [
        {
            "text": (c.get("text") or "").strip(),
            "kind": c.get("kind") or "text",
            "image_url": c.get("image_url") or "",
        }
        for c in chunks
        if (c.get("text") or "").strip()
    ]
    if not segments:
        raise KnowledgeBaseError("没有可导入的内容（chunk 均为空）")

    # 覆盖已入库文档时，校验归属：仅上传者本人可编辑。
    store = get_kb_milvus_client()
    if store.collection_exists():
        rows = store.query(expr=f'doc_id == "{doc_id}"', output_fields=["owner_id"], limit=_QUERY_LIMIT)
        if rows and any(row["owner_id"] != owner_id for row in rows):
            raise PermissionDeniedError("无权覆盖该文档（仅上传者可编辑）")

    count = _embed_and_upsert(doc_id, filename, scope, owner_id, segments)
    return {"doc_id": doc_id, "filename": filename, "chunks": count, "scope": scope}


def import_document(filename: str, raw: bytes, scope: str, owner_id: int) -> dict:
    """一步导入：解析+切分（preview_document）后直接向量化入库（commit_chunks）。"""
    preview = preview_document(filename, raw, scope)
    return commit_chunks(preview["doc_id"], filename, scope, owner_id, preview["chunks"])


def get_document_chunks(doc_id: str, owner_id: int) -> list[dict]:
    """返回某已入库文档的全部分片（按 chunk_index 排序），供「再次预览/编辑」。

    可见性：全局文档或本人文档可查看；他人 personal 文档拒绝。
    """
    _require_kb()
    if not _DOC_ID_RE.match(doc_id):
        raise DocumentNotFoundError("文档不存在")
    store = get_kb_milvus_client()
    if not store.collection_exists():
        raise DocumentNotFoundError("文档不存在")
    rows = store.query(
        expr=f'doc_id == "{doc_id}"',
        output_fields=["text", "chunk_index", "kind", "image_url", "owner_id", "scope"],
        limit=_QUERY_LIMIT,
    )
    if not rows:
        raise DocumentNotFoundError("文档不存在")
    if rows[0].get("scope") != "global" and rows[0].get("owner_id") != owner_id:
        raise PermissionDeniedError("无权查看该文档")
    rows.sort(key=lambda r: r.get("chunk_index", 0))
    return [
        {
            "index": r.get("chunk_index", 0),
            "text": r.get("text", ""),
            "kind": r.get("kind", "text"),
            "image_url": r.get("image_url", ""),
        }
        for r in rows
    ]


def list_documents(owner_id: int) -> list[dict]:
    """列出当前用户可见的文档：全部 global + 自己的 personal，按文档聚合并统计片数。

    知识库未启用或集合尚不存在时返回空列表（列出是只读视图，无需报错）。
    """
    settings = get_settings()
    if not settings.kb_configured:
        return []
    store = get_kb_milvus_client()
    if not store.collection_exists():
        return []
    rows = store.query(
        expr=f'scope == "global" or owner_id == {owner_id}',
        output_fields=["doc_id", "filename", "scope", "owner_id"],
        limit=_QUERY_LIMIT,
    )
    docs: dict[str, dict] = {}
    for row in rows:
        doc = docs.get(row["doc_id"])
        if doc is None:
            docs[row["doc_id"]] = {
                "doc_id": row["doc_id"],
                "filename": row["filename"],
                "scope": row["scope"],
                "owner_id": row["owner_id"],
                "chunks": 1,
            }
        else:
            doc["chunks"] += 1
    return sorted(docs.values(), key=lambda d: d["filename"])


def delete_document(doc_id: str, owner_id: int) -> int:
    """删除指定文档（仅上传者可删），返回删除的分片数。

    文档不存在抛 DocumentNotFoundError，非本人文档抛 PermissionDeniedError。
    """
    settings = get_settings()
    if not settings.kb_configured:
        raise KnowledgeBaseError("知识库未启用")
    if not _DOC_ID_RE.match(doc_id):
        raise DocumentNotFoundError("文档不存在")
    store = get_kb_milvus_client()
    if not store.collection_exists():
        raise DocumentNotFoundError("文档不存在")
    rows = store.query(
        expr=f'doc_id == "{doc_id}"', output_fields=["owner_id"], limit=_QUERY_LIMIT
    )
    if not rows:
        raise DocumentNotFoundError("文档不存在")
    if any(row["owner_id"] != owner_id for row in rows):
        raise PermissionDeniedError("无权删除该文档（仅上传者可删除）")
    store.delete(expr=f'doc_id == "{doc_id}"')
    return len(rows)
