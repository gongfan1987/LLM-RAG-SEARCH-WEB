"""研究路由：起任务 / 读状态 / 读轨迹 / 调试追加。均要求登录。

业务委托给 app.research.service 与 state/memory 仓储；本文件只做归属校验与出入参封装。
调试追加接口与未来 Agent 写状态用的是同一套 repository.append_* 接口。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.research import service
from app.research.memory import repository as mem_repo
from app.research.state import repository as state_repo
from app.research.state.schema import (
    Assumption, Chart, DataPoint, Draft, Fact, Review,
)
from app.schemas.research import (
    AppendRequest, CreateResearchTaskRequest, ResearchTaskDetail,
    ResearchTaskSummary, TrajectoryResponse,
)

router = APIRouter(prefix="/api/research", tags=["research"])

# 调试追加：field → (schema, repository 函数)
_APPEND_MAP = {
    "assumptions": (Assumption, state_repo.append_assumptions),
    "facts": (Fact, state_repo.append_facts),
    "data_points": (DataPoint, state_repo.append_data_points),
    "charts": (Chart, state_repo.append_charts),
    "drafts": (Draft, state_repo.append_drafts),
    "reviews": (Review, state_repo.append_reviews),
}


def _owned(db: Session, current_user: User, task_id: int):
    task = state_repo.get(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该研究任务")
    return task


@router.post("/tasks", response_model=ResearchTaskDetail)
def create_task(
    payload: CreateResearchTaskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.start_research_task(db, current_user.id, payload.topic, payload.session_id)


@router.get("/tasks", response_model=list[ResearchTaskSummary])
def list_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return state_repo.list_for_user(db, current_user.id)


@router.get("/tasks/{task_id}", response_model=ResearchTaskDetail)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _owned(db, current_user, task_id)


@router.get("/tasks/{task_id}/trajectory", response_model=list[TrajectoryResponse])
def get_trajectory(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned(db, current_user, task_id)
    return [t for t in mem_repo.list_trajectories(db, current_user.id) if t.task_id == task_id]


@router.post("/tasks/{task_id}/append", response_model=ResearchTaskDetail)
def append_field(
    task_id: int,
    payload: AppendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned(db, current_user, task_id)
    if payload.field not in _APPEND_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的追加字段: {payload.field}")
    schema, append_fn = _APPEND_MAP[payload.field]
    items = [schema(**item) for item in payload.items]
    return append_fn(db, task_id, items)
