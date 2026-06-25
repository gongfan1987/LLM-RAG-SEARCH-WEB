"""会话路由：列表/创建/重命名/删除，均要求登录，业务逻辑委托给 session_service / message_service。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.message import MessageResponse
from app.schemas.session import SessionCreateRequest, SessionRenameRequest, SessionResponse
from app.services import message_service, session_service

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    return session_service.list_sessions(db, current_user)


@router.post("", response_model=SessionResponse)
def create_session(
    payload: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return session_service.create_session(db, current_user, payload)


@router.patch("/{session_id}", response_model=SessionResponse)
def rename_session(
    session_id: int,
    payload: SessionRenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return session_service.rename_session(db, current_user, session_id, payload)


@router.delete("/{session_id}")
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session_service.delete_session(db, current_user, session_id)
    return {"message": "会话已删除"}


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
def get_session_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    session = session_service.get_owned_session(db, current_user, session_id)
    return message_service.list_messages(db, session)
