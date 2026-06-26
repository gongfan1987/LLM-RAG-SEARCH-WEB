# ResearchState 全局共享状态 + 上下文 Memory 模块设计

- 日期：2026-06-26
- 范围：多 Agent 深度研究系统的「状态 + 记忆」底座（第一刀 spec）
- 状态：已评审通过，待写实现计划

## 1. 背景与目标

当前后端是**单 Agent 的 RAG 对话系统**：`chat_service` 编排 LLM + 知识库检索工具
（`rag_service`），尚无「多 Agent 研究」编排层。

本设计为后续的**多 Agent 深度研究系统**铺设两条记忆轴的底座：

| | ResearchState（任务内状态） | Memory（跨任务记忆） |
|---|---|---|
| 生命周期 | 单次研究任务，结束即归档 | 跨任务、长期，绑定用户 |
| 作用 | 多 Agent 在同一任务里接力协作的「共享工作台」 | 让系统记住用户，跨任务连贯 + 个性化 |
| 内容 | 大纲/假设/事实/数据点/图表/草稿/终稿/评审反馈 | 历史问题、研究偏好、任务轨迹 |

核心机制：ResearchState **只持续积累、不整体覆盖**，是 Agent 之间的通信总线
（Agent 不直接互相调用）；Memory 在任务结束时蒸馏沉淀、在新任务启动时注入回
ResearchState，形成「多轮连贯 + 个性化」闭环。

### 范围边界

- **本刀交付**：`app/research/` 数据模型 + 仓储/服务接口 + 只读（含调试写入）API +
  前端研究状态展示面板 + 单测。
- **本刀不含**：真正的多 Agent 编排（大纲/检索/写作/评审 Agent）——留作后续独立
  spec。前端展示的数据，在 Agent 落地前通过本刀的 `append` API / 测试夹具写入驱动；
  该 `append` API 正是未来 Agent 写状态用的同一套接口。
- **不做**：实时推送/SSE（前端先用轮询）；复杂偏好学习（先做显式直读 + 归档简单累积）。

## 2. 模块结构与目录

新增独立目录 `app/research/`，不塞进 `services/`：

```
backend/app/research/
├── __init__.py
├── state/
│   ├── models.py        # ResearchTask ORM（主表 + JSON 字段）
│   ├── schema.py        # Pydantic：Fact/DataPoint/Draft/Review 等子结构
│   └── repository.py    # 状态读 / 原子追加（行级锁）/ 整体更新 / 归档
├── memory/
│   ├── models.py        # UserResearchPreference ORM、TaskTrajectory ORM
│   ├── schema.py
│   ├── repository.py    # 偏好结构化直读 + 写入；轨迹写入
│   └── recall.py        # 历史/轨迹语义召回（复用 embedding + Milvus）
└── service.py           # 对外门面：起任务 / 注入记忆 / 读状态 / 归档蒸馏

backend/app/routers/research.py   # 只读 API + 调试写入
backend/app/schemas/research.py   # API 出入参
frontend/...                       # 研究状态展示面板（接读 API）
```

### 依赖方向

- `research/` 依赖 `app.llm`（embedding）、`app.utils.milvus`、`app.db`。
- `research/` **不被 `services/` 反向依赖**。
- 本层**不自己抓数据**：facts/data_points 的实际抓取未来由 Agent 调
  `rag_service` / `web_search` 后，通过本层 `append` 接口写入。本层只负责「存与传」。

## 3. ResearchState 数据模型与追加机制

### 3.1 主表 `research_tasks`（主表 + JSON 字段）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | PK | 任务 ID |
| `user_id` | FK / nullable | 归属用户（游客 null） |
| `session_id` | FK / nullable | 关联会话（打通现有对话） |
| `topic` | str | 研究主题 |
| `status` | enum | `drafting/researching/writing/reviewing/done/archived` |
| `version` | int | 乐观锁版本号（每次写回 +1） |
| `outline` | JSON | 研究大纲（分阶段，保留版本） |
| `assumptions` | JSON 数组 | 假设 |
| `facts` | JSON 数组 | 事实（带来源） |
| `data_points` | JSON 数组 | 数据点 |
| `charts` | JSON 数组 | 图表引用 |
| `drafts` | JSON 数组 | 草稿（多版） |
| `final` | JSON / null | 终稿 |
| `reviews` | JSON 数组 | 评审反馈 |
| `created_at` / `updated_at` | ts | |

### 3.2 子结构（`state/schema.py`，JSON 数组元素形态）

每个追加项自带来源与阶段标记，保证「只积累、可溯源、谁产出可追」：

```python
class Provenance(BaseModel):
    agent: str                     # 哪个 Agent 产出（如 "retriever"）
    source: str | None             # "kb:文件名" / "web:url" / "llm"
    created_at: datetime

class Fact(BaseModel):
    id: str                        # 追加项稳定 ID（去重/引用用）
    content: str
    provenance: Provenance

class DataPoint(BaseModel):
    id: str
    label: str; value: str; unit: str | None
    provenance: Provenance

class Draft(BaseModel):
    id: str; version: int; content: str
    provenance: Provenance

class Review(BaseModel):
    id: str; target_draft_id: str
    comments: list[str]; verdict: str   # approve / revise
    provenance: Provenance
```

`assumptions` / `charts` / `outline` 元素同理，均带 `id + provenance`。

### 3.3 追加机制（`state/repository.py`）—— 并发安全

支持「并行扁出」：Agent 并行干活，写回瞬间用**行级锁 + 读改写**串行化，
配 `version` 乐观锁兜底。

```python
def append_facts(db, task_id: int, items: list[Fact]) -> ResearchTask:
    task = db.query(ResearchTask)\
             .filter_by(id=task_id)\
             .with_for_update().one()      # 行锁，串行化本次写回
    existing = {f["id"] for f in task.facts}
    task.facts = task.facts + [
        f.model_dump() for f in items if f.id not in existing  # 幂等去重
    ]
    task.version += 1
    db.commit()
    return task
```

要点：
- 每个数组字段一个 `append_xxx`，**只追加、绝不整体覆盖**，Agent 各写各的字段。
- 按 `id` **幂等去重**，Agent 重试不产生重复。
- 锁粒度小：仅在 `append` 瞬间持行锁。
- `outline` / `final` 等「整体更新」语义用 `update_outline` / `set_final`，带
  `version` 校验，冲突则重读重试。

## 4. Memory 模块（跨任务记忆）

混合召回：**偏好结构化直读，历史/轨迹语义召回**。

### 4.1 研究偏好（结构化直读）

表 `user_research_preferences`，一个用户一行（`user_id` 唯一）：

| 列 | 说明 |
|---|---|
| `user_id` | FK 唯一 |
| `preferences` | JSON：`{depth, style, citation_required, focus_domains[], language}` |
| `updated_at` | |

- 显式部分：用户设置（深度/风格/是否要引用/关注领域）。
- 隐式沉淀：任务归档时由 `service.py` 从轨迹蒸馏累积（如多次研究金融 → 累积
  `focus_domains`）。先做显式直读 + 归档简单累积。
- 召回：新任务启动按 `user_id` 直读，注入初始 `outline` / 系统提示。游客无偏好则跳过。

### 4.2 历史问题 + 任务轨迹（语义召回）

表 `task_trajectories`——每个研究任务归档时写一条蒸馏摘要：

| 列 | 说明 |
|---|---|
| `id` / `user_id` | |
| `task_id` | 关联 `research_tasks` |
| `topic` | 主题 |
| `summary` | 归档蒸馏（终稿/大纲浓缩成一段） |
| `created_at` | |

召回链路（`memory/recall.py`，复用现有基建）：
1. 归档时 `summary` 经 `get_embedding_client().embed_query` 向量化，写入 Milvus
   `task_trajectory` 集合，按 `user_id` 过滤（复用 `rag_service._scope_filter` 同款
   owner 过滤思路）。
2. 新任务启动用新 `topic` 向量召回该用户 Top-K 相关历史轨迹。
3. **降级原则照搬 `rag_service`**：Milvus 未配置/失败 → 返回空、仅记日志，绝不阻断任务。

历史问题本身优先复用 `conversation_index_service` 已有会话索引，Memory 层仅在其不足时
补充，不重复造索引。

### 4.3 记忆注入（`service.py` 门面）

```python
def start_research_task(db, user_id, topic, session_id=None) -> ResearchTask:
    prefs = preference_repo.get(db, user_id)               # 结构化直读
    history = recall.related_trajectories(topic, user_id)  # 语义召回（可空）
    task = state_repo.create(db, user_id, topic, session_id)
    task.outline = build_seed_outline(topic, prefs, history)  # 记忆注入初始大纲
    db.commit()
    return task

def archive_task(db, task_id):                  # 任务结束 → 蒸馏回流 Memory
    task = state_repo.get(db, task_id)
    summary = distill(task)                      # 终稿/大纲浓缩
    trajectory_repo.add(db, task.user_id, task_id, task.topic, summary)
    recall.index_trajectory(...)                 # 向量入库
    preference_repo.accrue(db, task.user_id, task)  # 隐式偏好累积
    state_repo.set_status(db, task_id, "archived")
```

闭环：任务结束蒸馏进 Memory → 下次任务启动注入回 ResearchState。

## 5. API、前端展示与测试

### 5.1 只读 API（`routers/research.py`）

遵循现有 router 风格（`deps` 注入、归属校验复用 `session_service` 思路）：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/research/tasks` | 当前用户研究任务列表（轻量） |
| `GET` | `/research/tasks/{id}` | 单任务完整 ResearchState |
| `GET` | `/research/tasks/{id}/trajectory` | 任务蒸馏轨迹 |
| `POST` | `/research/tasks` | 起任务（注入记忆）——未来 Agent 入口，现作调试/驱动展示 |
| `POST` | `/research/tasks/{id}/append` | 调试用统一追加（`field` + `items`），走 repository 的 `append_xxx`，与未来 Agent 同一套接口 |

`schemas/research.py` 复用 `state/schema.py` 子结构。归属校验：非本人任务 403，游客
仅可见自己 session 内任务。

### 5.2 前端展示面板

按现有前端风格新增研究状态面板，对接读 API 分区呈现：
- 顶部：主题 + `status` 阶段进度条
- 大纲 / 假设 / 事实（带来源标签，可溯源）/ 数据点 / 图表 区
- 草稿版本切换 + 评审反馈
- 轮询读 API 刷新（实时推送留待 Agent spec）

### 5.3 测试策略（遵循 `.claude/rules/test.md`）

- 状态层：`append_xxx` 幂等性、并发追加不丢更新（两事务并发 append 断言两批都在）、
  `version` 递增、整体更新冲突重试。命名体现业务场景
  （如 `test_并行检索追加事实不丢失`）。
- Memory 层：偏好直读/缺省、轨迹蒸馏写入、语义召回**降级路径**（Milvus 不可用返回空、
  不抛错）——复用 `rag_service` 同款降级测试思路。
- 门面：`start_research_task` 注入记忆、`archive_task` 回流闭环。
- 不依赖真实外部服务：embedding/Milvus 用 mock/fake（优先复用项目已有 mock 方式）。
- API 层：归属校验（403）、只读返回结构。

## 6. 待后续 spec

- 多 Agent 编排骨架（大纲/检索/写作/评审 Agent 的角色与阶段流转）。
- 研究进度实时推送（SSE）。
- 偏好的复杂学习与个性化排序。
