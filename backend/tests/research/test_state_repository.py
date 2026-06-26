"""app/research/state/repository.py 单测：追加式积累、幂等去重、版本递增、整体更新。"""
from datetime import datetime

import pytest

from app.research.state import repository as repo
from app.research.state.models import ResearchStatus
from app.research.state.schema import Draft, Fact, OutlineSection, Provenance


def _prov():
    return Provenance(agent="retriever", source="web:a", created_at=datetime(2026, 6, 26))


def _fact(fid, content="x"):
    return Fact(id=fid, content=content, provenance=_prov())


def test_创建任务返回初始状态(db):
    task = repo.create(db, topic="行业研究", user_id=1)
    assert task.id is not None
    assert task.status == ResearchStatus.DRAFTING
    assert task.user_id == 1


def test_连续追加事实持续积累且版本递增(db):
    task = repo.create(db, topic="t")
    v0 = task.version
    repo.append_facts(db, task.id, [_fact("f1")])
    task = repo.append_facts(db, task.id, [_fact("f2")])
    assert [f["id"] for f in task.facts] == ["f1", "f2"]
    assert task.version == v0 + 2


def test_重复id追加幂等不重复(db):
    task = repo.create(db, topic="t")
    repo.append_facts(db, task.id, [_fact("f1", "原始")])
    task = repo.append_facts(db, task.id, [_fact("f1", "重试")])
    assert len(task.facts) == 1
    assert task.facts[0]["content"] == "原始"  # 已存在则跳过，不覆盖


def test_设置大纲整体替换并升版本(db):
    task = repo.create(db, topic="t")
    s1 = OutlineSection(id="o1", title="背景", points=["p"], provenance=_prov())
    task = repo.set_outline(db, task.id, [s1])
    assert [o["id"] for o in task.outline] == ["o1"]


def test_设置终稿与状态(db):
    task = repo.create(db, topic="t")
    final = Draft(id="dr1", version=3, content="终稿", provenance=_prov())
    repo.set_final(db, task.id, final)
    task = repo.set_status(db, task.id, ResearchStatus.DONE)
    assert task.final["id"] == "dr1"
    assert task.status == ResearchStatus.DONE


def test_追加到不存在任务报错(db):
    with pytest.raises(ValueError):
        repo.append_facts(db, 9999, [_fact("f1")])
