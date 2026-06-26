"""研究 API 出入参。详情/摘要直接映射 ResearchTask；追加复用 state.schema 子结构。"""
from datetime import datetime

from pydantic import BaseModel


class CreateResearchTaskRequest(BaseModel):
    topic: str
    session_id: int | None = None


class AppendRequest(BaseModel):
    field: str  # facts/data_points/assumptions/charts/drafts/reviews
    items: list[dict]


class ResearchTaskSummary(BaseModel):
    id: int
    topic: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResearchTaskDetail(ResearchTaskSummary):
    outline: list
    assumptions: list
    facts: list
    data_points: list
    charts: list
    drafts: list
    final: dict | None
    reviews: list


class TrajectoryResponse(BaseModel):
    id: int
    task_id: int
    topic: str
    summary: str
    created_at: datetime

    class Config:
        from_attributes = True
