"""ResearchTask 仓储：研究状态的读 / 追加式写 / 整体更新。

追加机制——支持多 Agent 并行扁出：Agent 并行干活，仅在写回瞬间用行级锁
（with_for_update）串行化「读改写」，按 id 幂等去重，version 自增兜底。
每个数组字段只追加、绝不整体覆盖。outline/final 这类整体语义用 set_xxx。
"""
from sqlalchemy.orm import Session

from app.research.state.models import ResearchTask
from app.research.state.schema import (
    Assumption, Chart, DataPoint, Draft, Fact, OutlineSection, Review,
)


def create(db: Session, topic: str, user_id: int | None = None, session_id: int | None = None) -> ResearchTask:
    task = ResearchTask(topic=topic, user_id=user_id, session_id=session_id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get(db: Session, task_id: int) -> ResearchTask | None:
    return db.get(ResearchTask, task_id)


def list_for_user(db: Session, user_id: int) -> list[ResearchTask]:
    return (
        db.query(ResearchTask)
        .filter(ResearchTask.user_id == user_id)
        .order_by(ResearchTask.created_at.desc())
        .all()
    )


def _locked(db: Session, task_id: int) -> ResearchTask:
    """行级锁取任务（sqlite 下 with_for_update 为 no-op，真实库才生效）。"""
    task = db.query(ResearchTask).filter(ResearchTask.id == task_id).with_for_update().first()
    if task is None:
        raise ValueError(f"研究任务不存在: {task_id}")
    return task


def _append(db: Session, task_id: int, field: str, dumped: list[dict]) -> ResearchTask:
    task = _locked(db, task_id)
    existing_ids = {item["id"] for item in getattr(task, field)}
    new_items = [d for d in dumped if d["id"] not in existing_ids]  # 幂等去重
    if new_items:
        setattr(task, field, getattr(task, field) + new_items)  # 重新赋值触发 ORM 脏检测
        task.version += 1
    db.commit()
    db.refresh(task)
    return task


def _dump(items) -> list[dict]:
    return [i.model_dump(mode="json") for i in items]


def append_assumptions(db, task_id, items: list[Assumption]) -> ResearchTask:
    return _append(db, task_id, "assumptions", _dump(items))


def append_facts(db, task_id, items: list[Fact]) -> ResearchTask:
    return _append(db, task_id, "facts", _dump(items))


def append_data_points(db, task_id, items: list[DataPoint]) -> ResearchTask:
    return _append(db, task_id, "data_points", _dump(items))


def append_charts(db, task_id, items: list[Chart]) -> ResearchTask:
    return _append(db, task_id, "charts", _dump(items))


def append_drafts(db, task_id, items: list[Draft]) -> ResearchTask:
    return _append(db, task_id, "drafts", _dump(items))


def append_reviews(db, task_id, items: list[Review]) -> ResearchTask:
    return _append(db, task_id, "reviews", _dump(items))


def set_outline(db: Session, task_id: int, sections: list[OutlineSection]) -> ResearchTask:
    task = _locked(db, task_id)
    task.outline = _dump(sections)  # 整体替换
    task.version += 1
    db.commit()
    db.refresh(task)
    return task


def set_final(db: Session, task_id: int, final: Draft) -> ResearchTask:
    task = _locked(db, task_id)
    task.final = final.model_dump(mode="json")
    task.version += 1
    db.commit()
    db.refresh(task)
    return task


def set_status(db: Session, task_id: int, status: str) -> ResearchTask:
    task = _locked(db, task_id)
    task.status = status
    db.commit()
    db.refresh(task)
    return task
