"""ResearchTask：研究任务的「共享工作台」主表。

主表存任务元信息；研究产物（大纲/假设/事实/数据点/图表/草稿/终稿/评审）
存 JSON 列，元素形态见 app.research.state.schema。version 为乐观锁版本号，
每次写回 +1。
"""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchStatus(StrEnum):
    DRAFTING = "drafting"
    RESEARCHING = "researching"
    WRITING = "writing"
    REVIEWING = "reviewing"
    DONE = "done"
    ARCHIVED = "archived"


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # nullable：本刀 API 要求登录，但保留空值以便后续支持游客。
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ResearchStatus.DRAFTING)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    outline: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    charts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    drafts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    final: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviews: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
