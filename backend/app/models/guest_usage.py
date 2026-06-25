from datetime import date

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GuestUsage(Base):
    """游客（未登录）每日调用次数计数，按 标识(anonymous_id 或 IP) + 日期 维度统计。"""

    __tablename__ = "guest_usages"
    __table_args__ = (UniqueConstraint("identity", "usage_date", name="uq_guest_identity_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    identity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
