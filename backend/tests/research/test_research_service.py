"""app/research/service.py 单测：起任务注入记忆、归档蒸馏回流闭环。

recall 用 monkeypatch 替身，避免触达 Milvus；DB 用 conftest 的 db 夹具。
"""
from app.research import service
from app.research.memory import repository as mem_repo
from app.research.state import repository as state_repo
from app.research.state.models import ResearchStatus


def test_起任务注入偏好与历史到大纲(db, monkeypatch):
    mem_repo.set_preference(db, user_id=1, preferences={"focus_domains": ["金融"]})
    monkeypatch.setattr(service.recall, "related_trajectories",
                        lambda topic, user_id, **k: [{"topic": "旧研究", "summary": "旧摘要"}])
    task = service.start_research_task(db, user_id=1, topic="新能源")
    # seed 大纲非空，且把历史/偏好作为线索注入（标题中体现）。
    assert len(task.outline) >= 1
    titles = " ".join(s["title"] for s in task.outline)
    assert "新能源" in titles


def test_归档写轨迹累积偏好并置状态(db, monkeypatch):
    monkeypatch.setattr(service.recall, "index_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(service.recall, "related_trajectories", lambda *a, **k: [])
    task = service.start_research_task(db, user_id=1, topic="光伏行业")
    archived = service.archive_task(db, task.id)
    assert archived.status == ResearchStatus.ARCHIVED
    assert len(mem_repo.list_trajectories(db, user_id=1)) == 1
    assert "光伏行业" in mem_repo.get_preference(db, user_id=1)["focus_domains"]
