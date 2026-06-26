"""Memory 仓储：研究偏好结构化直读/写入/累积、任务轨迹写入与读取。"""
from sqlalchemy.orm import Session

from app.research.memory.models import TaskTrajectory, UserResearchPreference


def get_preference(db: Session, user_id: int) -> dict:
    row = db.get(UserResearchPreference, user_id)
    return dict(row.preferences) if row else {}


def set_preference(db: Session, user_id: int, preferences: dict) -> UserResearchPreference:
    row = db.get(UserResearchPreference, user_id)
    if row is None:
        row = UserResearchPreference(user_id=user_id, preferences=preferences)
        db.add(row)
    else:
        row.preferences = preferences
    db.commit()
    db.refresh(row)
    return row


def accrue_preference(db: Session, user_id: int, topic: str) -> UserResearchPreference:
    """把本次研究主题累加进 focus_domains（去重）——隐式偏好沉淀。"""
    prefs = get_preference(db, user_id)
    domains = list(prefs.get("focus_domains", []))
    if topic not in domains:
        domains.append(topic)
    prefs["focus_domains"] = domains
    return set_preference(db, user_id, prefs)


def add_trajectory(db: Session, user_id: int | None, task_id: int, topic: str, summary: str) -> TaskTrajectory:
    row = TaskTrajectory(user_id=user_id, task_id=task_id, topic=topic, summary=summary)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_trajectories(db: Session, user_id: int) -> list[TaskTrajectory]:
    return (
        db.query(TaskTrajectory)
        .filter(TaskTrajectory.user_id == user_id)
        .order_by(TaskTrajectory.created_at.desc(), TaskTrajectory.id.desc())
        .all()
    )
