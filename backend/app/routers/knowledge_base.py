"""知识库路由：上传/列出/删除文档，均要求登录。

仅做参数解析与错误转换，业务流程委托给 knowledge_base_service。
切分/向量化/写库/查库均为阻塞 IO，统一放线程池执行，避免阻塞事件循环。
"""
import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.knowledge_base import (
    ChunkPreview,
    CommitChunksRequest,
    DocumentImportResponse,
    DocumentPreviewResponse,
    KnowledgeDocument,
)
from app.services import knowledge_base_service
from app.services.knowledge_base_service import (
    DocumentNotFoundError,
    KnowledgeBaseError,
    PermissionDeniedError,
)

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"])


def _to_http_error(exc: KnowledgeBaseError) -> HTTPException:
    """按异常类型映射 HTTP 状态码。"""
    if isinstance(exc, DocumentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/documents", response_model=DocumentImportResponse)
async def import_document(
    file: UploadFile = File(...),
    scope: str = Form("personal"),  # global（全局共享）| personal（仅自己可见）
    current_user: User = Depends(get_current_user),
):
    raw = await file.read()
    try:
        result = await asyncio.to_thread(
            knowledge_base_service.import_document,
            file.filename or "untitled",
            raw,
            scope,
            current_user.id,
        )
    except KnowledgeBaseError as exc:
        raise _to_http_error(exc) from exc
    return result


@router.post("/documents/preview", response_model=DocumentPreviewResponse)
async def preview_document(
    file: UploadFile = File(...),
    scope: str = Form("personal"),
    current_user: User = Depends(get_current_user),
):
    """解析+切分文档，返回可预览/编辑的 chunk 列表（不写入 Milvus）。"""
    raw = await file.read()
    try:
        return await asyncio.to_thread(
            knowledge_base_service.preview_document, file.filename or "untitled", raw, scope
        )
    except KnowledgeBaseError as exc:
        raise _to_http_error(exc) from exc


@router.post("/documents/commit", response_model=DocumentImportResponse)
async def commit_chunks(
    payload: CommitChunksRequest,
    current_user: User = Depends(get_current_user),
):
    """把（可能已编辑的）chunk 列表向量化写入 Milvus；用于确认导入或覆盖编辑。"""
    try:
        return await asyncio.to_thread(
            knowledge_base_service.commit_chunks,
            payload.doc_id,
            payload.filename,
            payload.scope,
            current_user.id,
            [c.model_dump() for c in payload.chunks],
        )
    except KnowledgeBaseError as exc:
        raise _to_http_error(exc) from exc


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkPreview])
async def get_document_chunks(
    doc_id: str,
    current_user: User = Depends(get_current_user),
) -> list:
    """查看某已入库文档的全部分片（供再次预览/编辑）。"""
    try:
        return await asyncio.to_thread(
            knowledge_base_service.get_document_chunks, doc_id, current_user.id
        )
    except KnowledgeBaseError as exc:
        raise _to_http_error(exc) from exc


@router.get("/documents", response_model=list[KnowledgeDocument])
async def list_documents(current_user: User = Depends(get_current_user)) -> list:
    """列出当前用户可见的文档：全部 global + 自己的 personal。"""
    return await asyncio.to_thread(knowledge_base_service.list_documents, current_user.id)


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        deleted = await asyncio.to_thread(
            knowledge_base_service.delete_document, doc_id, current_user.id
        )
    except KnowledgeBaseError as exc:
        raise _to_http_error(exc) from exc
    return {"message": "文档已删除", "deleted_chunks": deleted}
