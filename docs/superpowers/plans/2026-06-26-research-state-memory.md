# ResearchState 共享状态 + Memory 模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为多 Agent 深度研究系统铺设「任务内共享状态 ResearchState + 跨任务 Memory」底座：数据模型、并发安全的追加式仓储、记忆注入/回流服务、只读+调试写入 API、前端展示面板。

**Architecture:** 新增独立模块 `app/research/`，分 `state/`（ResearchTask 主表 + JSON 字段，行级锁追加）与 `memory/`（偏好结构化直读 + 轨迹语义召回，复用 embedding/Milvus）。`service.py` 作门面串起「起任务注入记忆 → 归档蒸馏回流」闭环。`routers/research.py` 暴露只读 API 与调试用统一追加接口（未来 Agent 写状态的同一套接口）。前端新增研究状态面板，轮询读 API 展示。

**Tech Stack:** FastAPI、SQLAlchemy 2.0（`DeclarativeBase` / `Mapped` / `mapped_column`，JSON 列）、Pydantic v2、pytest（边界 mock）、Next.js 16 App Router + React 19 + zustand。

## Global Constraints

- 不引入新依赖：复用现有 SQLAlchemy / Pydantic / FastAPI / pytest（后端），Next.js / zustand / `apiFetch`（前端）。
- ORM 模型遵循现有写法：`from app.db.base import Base`，`Mapped` + `mapped_column`，时间列用 `server_default=func.now()`。
- 检索/向量降级原则照搬 `rag_service`/`conversation_index_service`：未配置或失败 → 返回空 + 仅记日志，绝不抛错阻断主流程。
- 测试遵循 `.claude/rules/test.md`：命名体现业务场景（中文）、不依赖真实外部服务（embedding/Milvus 用替身）、优先复用 `tests/` 既有 mock 风格。
- commit message 遵循 `.claude/rules/git.md`：`type(scope): 中文描述`，scope 用 `research`。
- 本刀 API 要求登录（复用 `get_current_user`）；`research_tasks.user_id` 列保持 nullable 以便后续支持游客，但本刀不实现游客路径。
- `research/` 不被 `services/` 反向依赖；本层只「存与传」，不自己抓取数据。

---

### Task 1: ResearchState 子结构 Schema

纯 Pydantic 模型，无 DB 依赖。定义追加项的统一形态（每项自带 `id` + `provenance`）。

**Files:**
- Create: `backend/app/research/__init__.py`（空文件）
- Create: `backend/app/research/state/__init__.py`（空文件）
- Create: `backend/app/research/state/schema.py`
- Test: `backend/tests/research/test_state_schema.py`
- Create: `backend/tests/research/__init__.py`（空文件）

**Interfaces:**
- Produces: `Provenance(agent: str, source: str | None = None, created_at: datetime)`；`OutlineSection(id, title, points: list[str], provenance)`；`Assumption(id, content, status="open", provenance)`；`Fact(id, content, provenance)`；`DataPoint(id, label, value, unit: str | None, provenance)`；`Chart(id, title, chart_type, data_point_ids: list[str], image_url: str | None, provenance)`；`Draft(id, version: int, content, provenance)`；`Review(id, target_draft_id, comments: list[str], verdict, provenance)`。所有模型均为 `pydantic.BaseModel`，`.model_dump(mode="json")` 可序列化进 JSON 列。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_state_schema.py
"""app/research/state/schema.py 单测：追加项子结构可构造、可 JSON 序列化、含来源标记。"""
from datetime import datetime

from app.research.state.schema import (
    Assumption, Chart, DataPoint, Draft, Fact, OutlineSection, Provenance, Review,
)


def _prov() -> Provenance:
    return Provenance(agent="retriever", source="kb:报告.pdf", created_at=datetime(2026, 6, 26))


def test_事实项带来源且可json序列化():
    fact = Fact(id="f1", content="GDP 增长 5%", provenance=_prov())
    dumped = fact.model_dump(mode="json")
    assert dumped["id"] == "f1"
    assert dumped["provenance"]["agent"] == "retriever"
    assert dumped["provenance"]["source"] == "kb:报告.pdf"


def test_假设默认状态为open():
    a = Assumption(id="a1", content="市场将扩张", provenance=_prov())
    assert a.status == "open"


def test_数据点单位可缺省():
    dp = DataPoint(id="d1", label="GDP", value="5%", unit=None, provenance=_prov())
    assert dp.unit is None


def test_评审反馈关联草稿并带结论():
    r = Review(id="r1", target_draft_id="dr1", comments=["论据不足"], verdict="revise", provenance=_prov())
    assert r.target_draft_id == "dr1"
    assert r.verdict == "revise"


def test_大纲章节与图表与草稿可构造():
    OutlineSection(id="o1", title="背景", points=["p1"], provenance=_prov())
    Chart(id="c1", title="趋势", chart_type="line", data_point_ids=["d1"], image_url=None, provenance=_prov())
    Draft(id="dr1", version=1, content="草稿正文", provenance=_prov())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_state_schema.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.research'`）

- [ ] **Step 3: 写实现**

```python
# backend/app/research/state/schema.py
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
```

同时创建空的 `backend/app/research/__init__.py`、`backend/app/research/state/__init__.py`、`backend/tests/research/__init__.py`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_state_schema.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/research/__init__.py backend/app/research/state/__init__.py \
        backend/app/research/state/schema.py \
        backend/tests/research/__init__.py backend/tests/research/test_state_schema.py
git commit -m "feat(research): 新增 ResearchState 子结构 schema"
```

---

### Task 2: ResearchTask ORM 模型 + DB 测试夹具

主表 + JSON 字段；并新增全项目第一个 sqlite 内存 DB 夹具（后续仓储/服务测试复用）。

**Files:**
- Create: `backend/app/research/state/models.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/research/test_state_models.py`

**Interfaces:**
- Consumes: `app.db.base.Base`（Task 既有）。
- Produces:
  - `ResearchStatus`：StrEnum，值 `drafting/researching/writing/reviewing/done/archived`。
  - `ResearchTask` ORM，表名 `research_tasks`，列见实现；JSON 数组列默认空列表，`final` 可空。
  - pytest fixture `db`（function 作用域）：基于 sqlite 内存库的 `Session`，已建好所有表。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_state_models.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_state_models.py -v`
Expected: FAIL（`ModuleNotFoundError` / fixture `db` not found）

- [ ] **Step 3: 写实现**

```python
# backend/app/research/state/models.py
"""ResearchTask：研究任务的「共享工作台」主表。

主表存任务元信息；研究产物（大纲/假设/事实/数据点/图表/草稿/终稿/评审）
存 JSON 列，元素形态见 app.research.state.schema。version 为乐观锁版本号，
每次写回 +1。
"""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchStatus(StrEnum):
    DRAFTING = "drafting"
    RESEARCHING = "researching"
    WRITING = "writing"
    REVIEWING = "reviewing"
    DONE = "done"
    ARCHIVED = "archived"


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # nullable：本刀 API 要求登录，但保留空值以便后续支持游客。
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ResearchStatus.DRAFTING)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    outline: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    charts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    drafts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    final: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviews: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

```python
# backend/tests/conftest.py
"""测试夹具：提供基于 sqlite 内存库的 SQLAlchemy Session。

仅用于需要真实 DB 的仓储/服务单测；建表前导入全部 ORM 模型以注册到 Base.metadata。
注意：sqlite 不真正执行 SELECT ... FOR UPDATE 行锁，故并发锁语义需在真实
Postgres/MySQL 做集成验证；此处覆盖追加/去重/版本递增等可在单连接验证的逻辑。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base

# 导入模型以注册到 Base.metadata（建表需要）。
import app.models.user  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.research.state.models  # noqa: F401
import app.research.memory.models  # noqa: F401


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
```

> 注：conftest 导入了 `app.research.memory.models`（Task 4 创建）。先用以下占位让 Task 2 测试跑通，Task 4 会替换为真实模型：本步骤中**临时**注释掉 `import app.research.memory.models` 那一行，待 Task 4 创建该文件后取消注释。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_state_models.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/research/state/models.py backend/tests/conftest.py \
        backend/tests/research/test_state_models.py
git commit -m "feat(research): 新增 ResearchTask 主表模型与 sqlite 测试夹具"
```

---

### Task 3: 状态仓储（追加式 + 并发安全 + 整体更新）

**Files:**
- Create: `backend/app/research/state/repository.py`
- Test: `backend/tests/research/test_state_repository.py`

**Interfaces:**
- Consumes: `ResearchTask`、`ResearchStatus`（Task 2）；`Fact/DataPoint/Assumption/Chart/Draft/Review/OutlineSection`（Task 1）；`sqlalchemy.orm.Session`。
- Produces：
  - `create(db, topic, user_id=None, session_id=None) -> ResearchTask`
  - `get(db, task_id: int) -> ResearchTask | None`
  - `list_for_user(db, user_id: int) -> list[ResearchTask]`（按 `created_at` 倒序）
  - `append_assumptions/append_facts/append_data_points/append_charts/append_drafts/append_reviews(db, task_id, items) -> ResearchTask`（按 `id` 幂等去重，`version += 1`）
  - `set_outline(db, task_id, sections: list[OutlineSection]) -> ResearchTask`（整体替换，`version += 1`）
  - `set_final(db, task_id, final: Draft) -> ResearchTask`
  - `set_status(db, task_id, status: str) -> ResearchTask`
  - 失败：`task_id` 不存在抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_state_repository.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_state_repository.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

```python
# backend/app/research/state/repository.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_state_repository.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/research/state/repository.py backend/tests/research/test_state_repository.py
git commit -m "feat(research): 新增 ResearchState 追加式并发安全仓储"
```

---

### Task 4: Memory 模型 + 偏好/轨迹仓储（结构化直读）

**Files:**
- Create: `backend/app/research/memory/__init__.py`（空文件）
- Create: `backend/app/research/memory/models.py`
- Create: `backend/app/research/memory/repository.py`
- Test: `backend/tests/research/test_memory_repository.py`
- Modify: `backend/tests/conftest.py`（取消 Task 2 中注释的 `import app.research.memory.models`）

**Interfaces:**
- Consumes: `app.db.base.Base`、`ResearchTask`（Task 2）、`Session`。
- Produces：
  - ORM `UserResearchPreference`（表 `user_research_preferences`，`user_id` 唯一，`preferences` JSON，`updated_at`）。
  - ORM `TaskTrajectory`（表 `task_trajectories`，`id/user_id/task_id/topic/summary/created_at`）。
  - `get_preference(db, user_id) -> dict`（无记录返回 `{}`）
  - `set_preference(db, user_id, preferences: dict) -> UserResearchPreference`
  - `accrue_preference(db, user_id, topic: str) -> UserResearchPreference`（把 topic 累加进 `focus_domains`，去重）
  - `add_trajectory(db, user_id, task_id, topic, summary) -> TaskTrajectory`
  - `list_trajectories(db, user_id) -> list[TaskTrajectory]`（按 `created_at` 倒序）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_memory_repository.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_memory_repository.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

```python
# backend/app/research/memory/models.py
"""跨任务记忆的持久化模型：用户研究偏好（结构化直读）与任务轨迹（语义召回源）。"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserResearchPreference(Base):
    __tablename__ = "user_research_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # {depth, style, citation_required, focus_domains[], language}
    preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TaskTrajectory(Base):
    __tablename__ = "task_trajectories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
```

```python
# backend/app/research/memory/repository.py
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
        .order_by(TaskTrajectory.created_at.desc())
        .all()
    )
```

创建空的 `backend/app/research/memory/__init__.py`；在 `backend/tests/conftest.py` 取消注释 `import app.research.memory.models`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_memory_repository.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/research/memory/__init__.py backend/app/research/memory/models.py \
        backend/app/research/memory/repository.py backend/tests/conftest.py \
        backend/tests/research/test_memory_repository.py
git commit -m "feat(research): 新增 Memory 偏好与轨迹模型及仓储"
```

---

### Task 5: 轨迹语义召回（复用 embedding/Milvus，带降级）

**Files:**
- Create: `backend/app/research/memory/recall.py`
- Test: `backend/tests/research/test_memory_recall.py`

**Interfaces:**
- Consumes: `app.core.config.get_settings`、`app.llm.get_embedding_client`、`app.utils.milvus.get_milvus_client`（与 `conversation_index_service` 同款）。
- Produces：
  - `index_trajectory(trajectory_id: int, user_id: int | None, topic: str, summary: str) -> None`（best-effort，失败仅记日志）
  - `related_trajectories(topic: str, user_id: int, top_k: int = 3) -> list[dict]`（返回 `[{topic, summary}]`；未配置/失败/无 user_id 返回 `[]`）
  - 模块级 `_collection_ready: bool`（测试间需重置，复用现有约定）。
  - 集合名常量 `COLLECTION = "task_trajectory"`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_memory_recall.py
"""app/research/memory/recall.py 单测：轨迹向量化入库与语义召回，含降级路径。

mock：get_embedding_client / get_milvus_client / get_settings 全部替身，不触达真实服务。
"""
import pytest

import app.research.memory.recall as recall


class FakeEmbedding:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeStore:
    def __init__(self, fail=False, hits=None):
        self.fail = fail
        self._hits = hits or []
        self.inserted = []

    def ensure_collection(self, dim):
        pass

    def insert(self, data):
        if self.fail:
            raise RuntimeError("milvus down")
        self.inserted.append(data)

    def search(self, vector, limit, output_fields, expr):
        if self.fail:
            raise RuntimeError("milvus down")
        return self._hits


def _settings(milvus=True, embedding=True, dim=3):
    return type("S", (), {
        "milvus_configured": milvus, "embedding_configured": embedding, "milvus_dim": dim,
    })()


@pytest.fixture(autouse=True)
def reset_ready():
    recall._collection_ready = False
    yield
    recall._collection_ready = False


def test_未配置milvus召回返回空(monkeypatch):
    monkeypatch.setattr(recall, "get_settings", lambda: _settings(milvus=False))
    assert recall.related_trajectories("新能源", user_id=1) == []


def test_召回命中返回主题与摘要(monkeypatch):
    store = FakeStore(hits=[{"entity": {"topic": "光伏", "summary": "光伏摘要"}}])
    monkeypatch.setattr(recall, "get_settings", lambda: _settings())
    monkeypatch.setattr(recall, "get_embedding_client", lambda: FakeEmbedding())
    monkeypatch.setattr(recall, "get_milvus_client", lambda: store)
    out = recall.related_trajectories("新能源", user_id=1)
    assert out == [{"topic": "光伏", "summary": "光伏摘要"}]


def test_milvus失败召回降级为空不抛错(monkeypatch):
    store = FakeStore(fail=True)
    monkeypatch.setattr(recall, "get_settings", lambda: _settings())
    monkeypatch.setattr(recall, "get_embedding_client", lambda: FakeEmbedding())
    monkeypatch.setattr(recall, "get_milvus_client", lambda: store)
    assert recall.related_trajectories("新能源", user_id=1) == []


def test_入库失败静默不抛错(monkeypatch):
    store = FakeStore(fail=True)
    monkeypatch.setattr(recall, "get_settings", lambda: _settings())
    monkeypatch.setattr(recall, "get_embedding_client", lambda: FakeEmbedding())
    monkeypatch.setattr(recall, "get_milvus_client", lambda: store)
    recall.index_trajectory(1, user_id=1, topic="t", summary="s")  # 不抛异常即通过
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_memory_recall.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

```python
# backend/app/research/memory/recall.py
"""任务轨迹的语义召回：把归档摘要向量化入 Milvus，新任务按主题语义召回相关历史。

复用 embedding + Milvus 基建，降级原则照搬 conversation_index_service / rag_service：
未配置或任一步失败 → 返回空 / 静默跳过，仅记日志，绝不阻断研究任务。
"""
import logging

from app.core.config import get_settings
from app.llm import get_embedding_client
from app.utils.milvus import get_milvus_client

logger = logging.getLogger(__name__)

COLLECTION = "task_trajectory"
_collection_ready = False


def index_trajectory(trajectory_id: int, user_id: int | None, topic: str, summary: str) -> None:
    """把轨迹摘要向量化写入 Milvus（best-effort）。"""
    settings = get_settings()
    if not (settings.milvus_configured and settings.embedding_configured) or user_id is None:
        return
    try:
        vector = get_embedding_client().embed_query(summary)
        store = get_milvus_client()
        _ensure_collection(store, settings.milvus_dim or len(vector))
        store.insert([{
            "id": trajectory_id, "user_id": user_id,
            "topic": topic, "summary": summary, "vector": vector,
        }])
    except Exception as exc:  # noqa: BLE001 记忆入库失败不影响主流程
        logger.warning("轨迹入库失败（忽略）: %s", exc)


def related_trajectories(topic: str, user_id: int, top_k: int = 3) -> list[dict]:
    """按主题语义召回该用户最相关的历史轨迹；不可用/失败时返回 []。"""
    settings = get_settings()
    if not (settings.milvus_configured and settings.embedding_configured) or user_id is None:
        return []
    try:
        vector = get_embedding_client().embed_query(topic)
        store = get_milvus_client()
        hits = store.search(
            vector, limit=top_k,
            output_fields=["topic", "summary"],
            expr=f"user_id == {user_id}",
        )
    except Exception as exc:  # noqa: BLE001 检索是增强项，失败不阻断
        logger.warning("轨迹召回失败，已跳过: %s", exc)
        return []
    result = []
    for hit in hits:
        entity = hit.get("entity", hit)
        result.append({"topic": entity.get("topic", ""), "summary": entity.get("summary", "")})
    return result


def _ensure_collection(store, dim: int) -> None:
    global _collection_ready
    if not _collection_ready:
        store.ensure_collection(dim)
        _collection_ready = True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_memory_recall.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/research/memory/recall.py backend/tests/research/test_memory_recall.py
git commit -m "feat(research): 新增任务轨迹语义召回与降级处理"
```

---

### Task 6: 服务门面（起任务注入记忆 / 归档蒸馏回流）

**Files:**
- Create: `backend/app/research/service.py`
- Test: `backend/tests/research/test_research_service.py`

**Interfaces:**
- Consumes: `state.repository`（Task 3）、`memory.repository`（Task 4）、`memory.recall`（Task 5）、`state.schema.OutlineSection/Provenance/Draft`、`ResearchStatus`。
- Produces：
  - `start_research_task(db, user_id: int | None, topic: str, session_id=None) -> ResearchTask`：建任务 → 读偏好 + 召回历史 → 写入 seed outline。
  - `archive_task(db, task_id: int) -> ResearchTask`：蒸馏摘要 → 写轨迹 + 入向量库 + 累积偏好 → 状态置 `archived`。
  - 私有 `_distill(task) -> str`、`_build_seed_outline(topic, prefs, history) -> list[OutlineSection]`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_research_service.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_research_service.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

```python
# backend/app/research/service.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_research_service.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/research/service.py backend/tests/research/test_research_service.py
git commit -m "feat(research): 新增研究任务门面与记忆注入回流闭环"
```

---

### Task 7: 只读 + 调试写入 API

**Files:**
- Create: `backend/app/schemas/research.py`
- Create: `backend/app/routers/research.py`
- Modify: `backend/app/main.py`（import 并 `include_router(research.router)`）
- Test: `backend/tests/research/test_research_router.py`

**Interfaces:**
- Consumes: `app.core.deps.get_current_user/get_db`、`app.models.user.User`、`service`（Task 6）、`state.repository`（Task 3）、`memory.repository`（Task 4）、`state.schema`。
- Produces: `APIRouter`，前缀 `/api/research`：
  - `POST /api/research/tasks`（body `{topic, session_id?}`）→ `ResearchTaskDetail`
  - `GET /api/research/tasks` → `list[ResearchTaskSummary]`
  - `GET /api/research/tasks/{id}` → `ResearchTaskDetail`（非本人 403，不存在 404）
  - `GET /api/research/tasks/{id}/trajectory` → `list[TrajectoryResponse]`
  - `POST /api/research/tasks/{id}/append`（body `{field, items}`）→ `ResearchTaskDetail`（调试用，复用 repository `append_*`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/research/test_research_router.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/research/test_research_router.py -v`
Expected: FAIL（`ImportError` / 404 路由不存在）

- [ ] **Step 3: 写实现**

```python
# backend/app/schemas/research.py
"""研究 API 出入参。详情/摘要直接映射 ResearchTask；追加复用 state.schema 子结构。"""
from datetime import datetime

from pydantic import BaseModel


class CreateResearchTaskRequest(BaseModel):
    topic: str
    session_id: int | None = None


class AppendRequest(BaseModel):
    field: str  # facts/data_points/assumptions/charts/drafts/reviews
    items: list[dict]


class ResearchTaskSummary(BaseModel):
    id: int
    topic: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResearchTaskDetail(ResearchTaskSummary):
    outline: list
    assumptions: list
    facts: list
    data_points: list
    charts: list
    drafts: list
    final: dict | None
    reviews: list


class TrajectoryResponse(BaseModel):
    id: int
    task_id: int
    topic: str
    summary: str
    created_at: datetime

    class Config:
        from_attributes = True
```

```python
# backend/app/routers/research.py
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
```

```python
# backend/app/main.py — 修改 import 与路由注册
from app.routers import auth, chat, knowledge_base, research, sessions
# ...
app.include_router(research.router)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/research/test_research_router.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 全量回归**

Run: `cd backend && pytest -q`
Expected: 全部 PASS（含既有测试不回归）

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/research.py backend/app/routers/research.py \
        backend/app/main.py backend/tests/research/test_research_router.py
git commit -m "feat(research): 新增研究任务只读与调试追加 API"
```

---

### Task 8: 前端研究状态展示面板

> 仓库前端无测试设施，故本任务为「构建 + 手动验证」，不含自动化测试，遵循现有 `lib/api` + `types` + App Router 约定。

**Files:**
- Create: `frontend/types/research.ts`
- Create: `frontend/lib/api/research.ts`
- Create: `frontend/app/research/page.tsx`

**Interfaces:**
- Consumes: `apiFetch`（`lib/api/client.ts`）。
- Produces: `fetchResearchTasks()` / `fetchResearchTask(id)` / `createResearchTask(payload)` / `appendResearchField(id, payload)`；研究面板页 `/research`。

- [ ] **Step 1: 定义类型**

```typescript
// frontend/types/research.ts
export interface Provenance {
  agent: string;
  source: string | null;
  created_at: string;
}

export interface ResearchTaskSummary {
  id: number;
  topic: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ResearchTaskDetail extends ResearchTaskSummary {
  outline: Array<{ id: string; title: string; points: string[]; provenance: Provenance }>;
  assumptions: Array<Record<string, unknown>>;
  facts: Array<{ id: string; content: string; provenance: Provenance }>;
  data_points: Array<Record<string, unknown>>;
  charts: Array<Record<string, unknown>>;
  drafts: Array<Record<string, unknown>>;
  final: Record<string, unknown> | null;
  reviews: Array<Record<string, unknown>>;
}

export interface CreateResearchTaskPayload {
  topic: string;
  session_id?: number;
}
```

- [ ] **Step 2: 定义 API 模块**

```typescript
// frontend/lib/api/research.ts
import { apiFetch } from "@/lib/api/client";
import type {
  CreateResearchTaskPayload,
  ResearchTaskDetail,
  ResearchTaskSummary,
} from "@/types/research";

export function fetchResearchTasks(): Promise<ResearchTaskSummary[]> {
  return apiFetch<ResearchTaskSummary[]>("/api/research/tasks");
}

export function fetchResearchTask(id: number): Promise<ResearchTaskDetail> {
  return apiFetch<ResearchTaskDetail>(`/api/research/tasks/${id}`);
}

export function createResearchTask(
  payload: CreateResearchTaskPayload
): Promise<ResearchTaskDetail> {
  return apiFetch<ResearchTaskDetail>("/api/research/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function appendResearchField(
  id: number,
  payload: { field: string; items: Array<Record<string, unknown>> }
): Promise<ResearchTaskDetail> {
  return apiFetch<ResearchTaskDetail>(`/api/research/tasks/${id}/append`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 3: 实现研究状态面板**

```tsx
// frontend/app/research/page.tsx
"use client";

import { useCallback, useEffect, useState } from "react";

import { createResearchTask, fetchResearchTask, fetchResearchTasks } from "@/lib/api/research";
import type { ResearchTaskDetail, ResearchTaskSummary } from "@/types/research";

const STAGES = ["drafting", "researching", "writing", "reviewing", "done", "archived"];

export default function ResearchPage() {
  const [tasks, setTasks] = useState<ResearchTaskSummary[]>([]);
  const [active, setActive] = useState<ResearchTaskDetail | null>(null);
  const [topic, setTopic] = useState("");

  const loadTasks = useCallback(async () => setTasks(await fetchResearchTasks()), []);
  useEffect(() => { void loadTasks(); }, [loadTasks]);

  // 轮询刷新当前任务状态（实时推送留待 Agent spec）。
  useEffect(() => {
    if (!active) return;
    const id = setInterval(async () => setActive(await fetchResearchTask(active.id)), 3000);
    return () => clearInterval(id);
  }, [active?.id]);

  async function handleCreate() {
    if (!topic.trim()) return;
    const created = await createResearchTask({ topic: topic.trim() });
    setTopic("");
    setActive(created);
    await loadTasks();
  }

  return (
    <main style={{ display: "flex", gap: 24, padding: 24 }}>
      <aside style={{ width: 260 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="研究主题" />
          <button onClick={handleCreate}>新建</button>
        </div>
        <ul>
          {tasks.map((t) => (
            <li key={t.id}>
              <button onClick={async () => setActive(await fetchResearchTask(t.id))}>
                {t.topic}（{t.status}）
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {active && (
        <section style={{ flex: 1 }}>
          <h2>{active.topic}</h2>
          <ProgressBar status={active.status} />
          <Section title="大纲">
            {active.outline.map((o) => (
              <div key={o.id}><strong>{o.title}</strong>: {o.points.join("；")}</div>
            ))}
          </Section>
          <Section title="事实（可溯源）">
            {active.facts.map((f) => (
              <div key={f.id}>{f.content} <small>[{f.provenance.source ?? f.provenance.agent}]</small></div>
            ))}
          </Section>
          <Section title="数据点">{json(active.data_points)}</Section>
          <Section title="图表">{json(active.charts)}</Section>
          <Section title="草稿">{json(active.drafts)}</Section>
          <Section title="评审反馈">{json(active.reviews)}</Section>
        </section>
      )}
    </main>
  );
}

function ProgressBar({ status }: { status: string }) {
  const idx = STAGES.indexOf(status);
  return (
    <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
      {STAGES.map((s, i) => (
        <span key={s} style={{ fontWeight: i === idx ? 700 : 400, opacity: i <= idx ? 1 : 0.4 }}>{s}</span>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 16 }}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function json(data: unknown) {
  return <pre style={{ fontSize: 12 }}>{JSON.stringify(data, null, 2)}</pre>;
}
```

- [ ] **Step 4: 手动验证**

```bash
# 终端 A：起后端
cd backend && uvicorn app.main:app --reload
# 终端 B：起前端
cd frontend && npm run dev
```
浏览器访问 `/research`（需先登录拿到 token）：
1. 输入主题点「新建」→ 列表出现该任务，右侧显示 seed 大纲与进度条停在 `drafting`。
2. 用 `curl` 或调试 append 接口往 `facts` 追加一条 → 3 秒内面板「事实」区出现该条并显示来源标签。
Expected: 新建任务可见、seed 大纲已注入、轮询刷新生效。

- [ ] **Step 5: 提交**

```bash
git add frontend/types/research.ts frontend/lib/api/research.ts frontend/app/research/page.tsx
git commit -m "feat(research): 新增研究状态展示面板"
```

---

## 完成标准

- `cd backend && pytest -q` 全绿（新增约 26 个用例 + 既有不回归）。
- `/api/research/*` 可起任务（注入记忆 seed 大纲）、读状态、读轨迹、调试追加；归属校验生效。
- 前端 `/research` 面板可展示 ResearchState 各区并轮询刷新。
- 后续 spec（多 Agent 编排、SSE 实时推送、偏好学习）在此底座上接续。
