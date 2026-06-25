"""依赖注入：DB Session、当前用户解析（区分游客模式 / 登录模式）。
这里只做“从请求中取数据 + 调用 security 解析 token”，不包含业务规则；
具体业务规则（比如游客限额判断、用户是否存在）放在 services 层。
"""
from typing import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.base import SessionLocal
from app.models.user import User

# auto_error=False：允许匿名访问（游客模式），由各路由自行判断是否需要登录
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_optional_current_user(
    token: str | None = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """解析 token，若无 token 或 token 无效，返回 None（视为游客）。"""
    if not token:
        return None
    user_id = decode_access_token(token)
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    return user


def get_current_user(
    user: User | None = Depends(get_optional_current_user),
) -> User:
    """要求必须登录的接口使用此依赖。"""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    return user


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_anonymous_id(request: Request) -> str | None:
    """从请求头 X-Anonymous-Id 读取游客匿名标识（前端本地生成并持久化）。"""
    value = request.headers.get("x-anonymous-id")
    return value.strip() if value and value.strip() else None
