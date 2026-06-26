"""app/research/state/models.py 单测：ResearchTask 默认值与可持久化。"""
from app.research.state.models import ResearchStatus, ResearchTask


def test_新建任务默认状态与空集合(db):
    task = ResearchTask(topic="新能源行业研究")
    db.add(task)
    db.commit()
    db.refresh(task)

    assert task.id is not None
    assert task.status == ResearchStatus.DRAFTING
    assert task.version == 1
    assert task.facts == []
    assert task.outline == []
    assert task.final is None


def test_json字段可写入并读回(db):
    task = ResearchTask(topic="t", facts=[{"id": "f1", "content": "x"}])
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.facts[0]["id"] == "f1"
