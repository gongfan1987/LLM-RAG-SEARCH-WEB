"""app/research/memory/repository.py 单测：偏好结构化直读/写入/累积、轨迹写入与读取。"""
from app.research.memory import repository as repo


def test_无偏好返回空字典(db):
    assert repo.get_preference(db, user_id=1) == {}


def test_写入并读回偏好(db):
    repo.set_preference(db, user_id=1, preferences={"depth": "deep", "focus_domains": ["金融"]})
    assert repo.get_preference(db, user_id=1)["depth"] == "deep"


def test_累积关注领域去重(db):
    repo.set_preference(db, user_id=1, preferences={"focus_domains": ["金融"]})
    repo.accrue_preference(db, user_id=1, topic="金融")      # 已有不重复
    pref = repo.accrue_preference(db, user_id=1, topic="新能源")  # 新增
    assert pref.preferences["focus_domains"] == ["金融", "新能源"]


def test_轨迹写入并按时间倒序读取(db):
    repo.add_trajectory(db, user_id=1, task_id=10, topic="A", summary="摘要A")
    repo.add_trajectory(db, user_id=1, task_id=11, topic="B", summary="摘要B")
    trajectories = repo.list_trajectories(db, user_id=1)
    assert [t.topic for t in trajectories] == ["B", "A"]
