"""会话（ChatSession）相关业务逻辑：创建、列表、重命名、删除，均按用户隔离。"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
from app.models.user import User
from app.schemas.session import SessionCreateRequest, SessionRenameRequest

DEFAULT_SESSION_TITLE = "新对话"


def list_sessions(db: Session, user: User) -> list[ChatSession]:
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )


def create_session(db: Session, user: User, payload: SessionCreateRequest) -> ChatSession:
    title = payload.title.strip() if payload.title and payload.title.strip() else DEFAULT_SESSION_TITLE
    session = ChatSession(user_id=user.id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_owned_session(db: Session, user: User, session_id: int) -> ChatSession:
    """获取会话并校验归属，未找到或不属于当前用户时统一返回 404，避免泄露会话存在性。"""
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


def rename_session(db: Session, user: User, session_id: int, payload: SessionRenameRequest) -> ChatSession:
    session = get_owned_session(db, user, session_id)
    session.title = payload.title.strip()
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, user: User, session_id: int) -> None:
    session = get_owned_session(db, user, session_id)
    db.delete(session)
    db.commit()
