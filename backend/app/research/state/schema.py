"""ResearchState 各追加项的子结构。

每个追加项自带稳定 id（去重/引用用）与 Provenance（来源标记），
保证状态「只积累、可溯源、谁产出可追」。这些模型 model_dump(mode="json")
后存进 ResearchTask 的 JSON 列。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """统一来源标记：哪个 Agent、来自哪里、何时产出。"""
    agent: str
    source: str | None = None  # "kb:文件名" / "web:url" / "llm"
    created_at: datetime


class OutlineSection(BaseModel):
    id: str
    title: str
    points: list[str] = Field(default_factory=list)
    provenance: Provenance


class Assumption(BaseModel):
    id: str
    content: str
    status: str = "open"  # open / confirmed / refuted
    provenance: Provenance


class Fact(BaseModel):
    id: str
    content: str
    provenance: Provenance


class DataPoint(BaseModel):
    id: str
    label: str
    value: str
    unit: str | None = None
    provenance: Provenance


class Chart(BaseModel):
    id: str
    title: str
    chart_type: str  # line / bar / pie ...
    data_point_ids: list[str] = Field(default_factory=list)
    image_url: str | None = None
    provenance: Provenance


class Draft(BaseModel):
    id: str
    version: int
    content: str
    provenance: Provenance


class Review(BaseModel):
    id: str
    target_draft_id: str
    comments: list[str] = Field(default_factory=list)
    verdict: str  # approve / revise
    provenance: Provenance
