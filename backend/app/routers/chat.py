"""对话路由：负责接收请求、识别游客/登录身份、将 SSE 流转发给客户端。
具体的限额判断、上下文拼接、调用第三方 LLM 等业务逻辑全部在 chat_service 中完成。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.core.deps import get_anonymous_id, get_client_ip, get_db, get_optional_current_user
from app.models.user import User
from app.schemas.chat import ChatStreamRequest
from app.services import chat_service, guest_quota_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(
    payload: ChatStreamRequest,
    current_user: User | None = Depends(get_optional_current_user),
    client_ip: str = Depends(get_client_ip),
    anonymous_id: str | None = Depends(get_anonymous_id),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    guest_identity = None
    if current_user is None:
        guest_identity = guest_quota_service.resolve_guest_identity(anonymous_id, client_ip)

    generator = chat_service.stream_chat_reply(
        db=db,
        payload=payload,
        user=current_user,
        guest_identity=guest_identity,
    )
    return StreamingResponse(generator, media_type="text/event-stream")
