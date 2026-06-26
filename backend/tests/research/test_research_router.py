"""app/routers/research.py 单测：起任务、归属校验、调试追加。

用 FastAPI TestClient + 依赖覆盖：get_db 用 conftest 的 db 夹具，get_current_user 用伪用户。
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user, get_db
from app.main import app


@pytest.fixture
def client(db):
    fake_user = type("U", (), {"id": 1})()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_创建并读取研究任务(client):
    created = client.post("/api/research/tasks", json={"topic": "新能源"}).json()
    assert created["topic"] == "新能源"
    got = client.get(f"/api/research/tasks/{created['id']}").json()
    assert got["id"] == created["id"]
    assert got["outline"]  # seed 大纲已注入


def test_调试追加事实(client):
    created = client.post("/api/research/tasks", json={"topic": "t"}).json()
    item = {"id": "f1", "content": "事实1",
            "provenance": {"agent": "debug", "source": None, "created_at": "2026-06-26T00:00:00"}}
    resp = client.post(f"/api/research/tasks/{created['id']}/append",
                       json={"field": "facts", "items": [item]})
    assert resp.status_code == 200
    assert resp.json()["facts"][0]["id"] == "f1"


def test_访问他人任务返回403(client, db):
    from app.research.state import repository as state_repo
    other = state_repo.create(db, topic="别人的", user_id=999)
    assert client.get(f"/api/research/tasks/{other.id}").status_code == 403
