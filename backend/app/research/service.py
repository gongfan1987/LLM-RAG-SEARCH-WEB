"""研究任务门面：串起「起任务注入记忆 → 归档蒸馏回流」闭环。

Agent 编排（后续 spec）通过本门面起/结束任务，通过 state.repository 读写状态。
本层不感知 LLM 细节；蒸馏当前用规则化拼接，后续可替换为 LLM 摘要。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.research.memory import recall
from app.research.memory import repository as mem_repo
from app.research.state import repository as state_repo
from app.research.state.models import ResearchStatus, ResearchTask
from app.research.state.schema import OutlineSection, Provenance


def start_research_task(
    db: Session, user_id: int | None, topic: str, session_id: int | None = None
) -> ResearchTask:
    prefs = mem_repo.get_preference(db, user_id) if user_id is not None else {}
    history = recall.related_trajectories(topic, user_id) if user_id is not None else []
    task = state_repo.create(db, topic=topic, user_id=user_id, session_id=session_id)
    sections = _build_seed_outline(topic, prefs, history)
    return state_repo.set_outline(db, task.id, sections)


def archive_task(db: Session, task_id: int) -> ResearchTask:
    task = state_repo.get(db, task_id)
    if task is None:
        raise ValueError(f"研究任务不存在: {task_id}")
    summary = _distill(task)
    trajectory = mem_repo.add_trajectory(db, task.user_id, task.id, task.topic, summary)
    recall.index_trajectory(trajectory.id, task.user_id, task.topic, summary)
    if task.user_id is not None:
        mem_repo.accrue_preference(db, task.user_id, task.topic)
    return state_repo.set_status(db, task.id, ResearchStatus.ARCHIVED)


def _distill(task: ResearchTask) -> str:
    """把终稿/大纲浓缩成一段轨迹摘要（规则化；后续可换 LLM）。"""
    if task.final and task.final.get("content"):
        return task.final["content"][:500]
    points = [s.get("title", "") for s in task.outline]
    return f"{task.topic}：" + "；".join(p for p in points if p)


def _build_seed_outline(topic: str, prefs: dict, history: list[dict]) -> list[OutlineSection]:
    """把主题、偏好、历史召回拼成初始大纲——记忆注入的落点。"""
    prov = Provenance(agent="memory", source="llm", created_at=datetime.now())
    points: list[str] = []
    if prefs.get("focus_domains"):
        points.append("关注领域：" + "、".join(prefs["focus_domains"]))
    for h in history:
        points.append(f"相关历史：{h.get('topic', '')}")
    return [OutlineSection(id="seed", title=f"{topic} 研究大纲", points=points, provenance=prov)]
