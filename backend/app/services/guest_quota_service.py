"""游客（未登录）每日额度管理业务逻辑。

规则：以 (anonymous_id 或 IP, 当日日期) 为维度计数，超过 GUEST_DAILY_LIMIT 则拒绝。
登录用户不受此限制，由调用方（chat_service）决定是否走此流程。
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.guest_usage import GuestUsage
from app.utils.time import today_utc_date

settings = get_settings()


def resolve_guest_identity(anonymous_id: str | None, client_ip: str) -> str:
    """游客标识优先使用前端传入的匿名ID，缺失时回退到 IP。"""
    return anonymous_id.strip() if anonymous_id and anonymous_id.strip() else f"ip:{client_ip}"


def check_and_increment_quota(db: Session, identity: str) -> None:
    """校验今日剩余额度，若有额度则计数+1，否则抛出 429。"""
    usage_date = today_utc_date()

    usage = (
        db.query(GuestUsage)
        .filter(GuestUsage.identity == identity, GuestUsage.usage_date == usage_date)
        .first()
    )

    if usage is None:
        usage = GuestUsage(identity=identity, usage_date=usage_date, count=0)
        db.add(usage)

    if usage.count >= settings.guest_daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"游客每日试用次数已用完（{settings.guest_daily_limit}次），请登录后继续使用",
        )

    usage.count += 1
    db.add(usage)
    db.commit()
