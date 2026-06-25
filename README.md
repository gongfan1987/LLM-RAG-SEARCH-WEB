# AI 对话应用

参考 DeepSeek 风格的网页版 AI 对话产品。支持游客免登录试用与注册用户长期使用两种路径，核心是流式（SSE）AI 问答 + 历史会话管理。

## 1. 产品定位与目标用户

- 想快速体验 AI 对话、不想注册的访客
- 需要长期保存对话历史、多会话管理的注册用户

## 2. 核心功能

### 2.1 游客试用
- 未登录可直接进入聊天界面提问
- 按 `anonymous_id`（前端生成并持久化）或客户端 IP 做每日次数限额，默认 5 次/天（`GUEST_DAILY_LIMIT` 可配置）
- 超出限额返回 429，前端弹出引导登录的限额提示（`GuestLimitDialog`）
- 游客对话不落库，不保留历史

### 2.2 账号体系
- 注册 / 登录（用户名+密码，JWT 鉴权）
- 查看当前用户信息、修改密码
- 登录后不受次数限制

### 2.3 会话与消息
- 登录用户可创建、重命名、删除会话（`chat_sessions`）
- 每个会话保存完整消息记录（`chat_messages`），支持查看历史
- 侧边栏按时间分组展示会话列表（`ChatSidebar` + `groupSessionsByDate`）

### 2.4 对话能力
- 通过 `/api/chat/stream` 以 SSE 流式返回 AI 回复，前端逐字渲染
- 后端通过 OpenAI 兼容协议调用第三方 LLM（默认接入 DeepSeek 思考模式 `deepseek-reasoner`，模型/Base URL/Key 均可配置）
- 思考模式下展示模型思维链：AI 气泡上方有可折叠的「💭 思考过程」区块（`MessageBubble`），思维链仅用于展示，不落库、不回灌进后续上下文（历史消息只保留最终回复）
- 支持代码块高亮与一键复制（`CodeBlock` + `CopyButton`）

### 2.5 设置
- 个人设置页（`/settings`），含修改密码等账号管理操作

## 3. 主要页面

| 路径 | 说明 |
| --- | --- |
| `/` | 首页 |
| `/login`、`/register` | 登录、注册 |
| `/chat` | 主对话界面（侧边栏 + 消息列表 + 输入框） |
| `/settings` | 账号设置 |

## 4. 技术架构

### 4.1 整体架构

```
┌─────────────┐        HTTPS / SSE        ┌──────────────────┐        OpenAI 兼容协议        ┌────────────────┐
│   Frontend   │ ───────────────────────▶ │  Backend (FastAPI) │ ───────────────────────────▶ │ 第三方 LLM 服务 │
│  Next.js     │ ◀─────────────────────── │                    │ ◀─────────────────────────── │ (DeepSeek 等)   │
└─────────────┘                           └──────────────────┘                                └────────────────┘
                                                    │
                                                    ▼
                                              ┌──────────┐
                                              │  MySQL    │
                                              └──────────┘
```

### 4.2 技术栈

| 层 | 技术 |
| --- | --- |
| 前端框架 | Next.js（App Router）+ TypeScript |
| 前端状态管理 | Zustand |
| 后端框架 | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.x（Mapped/mapped_column 风格） |
| 数据库驱动 | PyMySQL（MySQL） |
| 鉴权 | JWT（python-jose）+ bcrypt 密码哈希（passlib） |
| LLM 调用 | httpx，OpenAI 兼容协议（chat/completions，流式） |
| 配置管理 | pydantic-settings，统一从 `.env` 读取，禁止硬编码密钥 |

### 4.3 后端分层架构

```
backend/app/
├── main.py     # 应用入口：挂载中间件、路由，启动时建表
├── core/       # config（配置）/ security（JWT+密码哈希）/ deps（依赖注入）
├── db/         # engine、SessionLocal、Base
├── models/     # ORM 模型
├── schemas/    # Pydantic 请求/响应模型
├── services/   # 业务逻辑层
├── routers/    # 路由层
└── utils/      # 无业务含义的纯工具函数
```

**分层职责与约束**（对应 `.claude/rules/architecture.md`）：
- **routers**：只做参数解析、依赖注入、组装响应，不直接操作 ORM、不写业务规则。
- **services**：承载全部业务规则——鉴权流程、会话归属校验、游客限额判断、LLM 请求拼接与调用。
- **core**：纯技术能力（JWT 编解码、密码哈希、依赖注入获取 DB/当前用户），不包含业务判断。
- **utils**：无业务含义的辅助函数（如时间格式化），业务规则不允许下沉到这一层。

**鉴权与身份解析**（`core/deps.py` + `core/security.py`）：
- `OAuth2PasswordBearer(auto_error=False)`：允许匿名请求，由各路由自行决定是否强制登录。
- `get_optional_current_user`：解析 JWT，无 token 或无效 token 时返回 `None`（视为游客），不抛异常。
- `get_current_user`：基于上者，若为 `None` 则抛 401，用于强制登录的路由（sessions、auth/me 等）。
- `get_client_ip` / `get_anonymous_id`：分别从 `X-Forwarded-For` 头和 `X-Anonymous-Id` 头取游客身份线索。
- JWT：`sub` 存用户 ID，有效期 `JWT_EXPIRE_MINUTES`（默认 7 天），密钥/算法均来自配置。

**路由与业务服务对照**：

| 路由 | 前缀 | 是否要求登录 | 对应 service |
| --- | --- | --- | --- |
| `auth.py` | `/api/auth` | 部分（register/login 不需要，me/change-password 需要） | `auth_service` |
| `sessions.py` | `/api/sessions` | 是 | `session_service` / `message_service` |
| `chat.py` | `/api/chat` | 否（区分游客/登录两条路径） | `chat_service` / `guest_quota_service` |

**对话流式架构**（`chat_service.stream_chat_reply`）：

核心设计约束：**`StreamingResponse` 一旦开始 yield，HTTP 200 已发出，此时不能再 `raise HTTPException`**（否则连接异常中断而非返回正常错误响应）。因此游客超额、会话不存在、LLM 调用失败等所有错误，统一转换为 SSE 事件帧 `{"type": "error", "error": "..."}` yield 给前端，再正常 `return` 结束流。SSE 事件类型：`session`（新会话 id）、`delta`（最终回复增量文本）、`reasoning`（思考模式下的思维链增量）、`error`、`done`。

流程：
1. 判断 `user` 是否为 `None`：登录则解析/创建会话并落库用户消息，再 yield `session` 事件；游客则通过 `guest_quota_service` 校验每日额度（超额转为 SSE error）。
2. `_build_context_messages`：拼接 system prompt + 历史消息（仅登录会话有历史）+ 当前用户输入。
3. `_stream_llm_reply`：httpx 流式 POST 第三方 `chat/completions`，逐段产出 `(kind, text)`——`reasoning`（来自 `delta.reasoning_content`，思考模式专有）转为 SSE `reasoning` 事件透传，`content`（来自 `delta.content`）转为 SSE `delta` 事件；异常统一包装为内部 `_LlmCallError` 再转 SSE error。
4. 登录用户在流结束后，将完整 assistant 回复（仅 `content` 部分）落库；思维链不落库、不回灌上下文；游客模式不落库。

**游客限额**（`guest_quota_service`）：
- 维度：`(identity, usage_date)` 唯一约束，identity 优先取前端 `anonymous_id`，否则回退 `ip:{client_ip}`。
- 达到 `GUEST_DAILY_LIMIT`（默认 5）则转 SSE error，否则 count+1。
- 时间基准用 `today_utc_date()`，避免与服务器本地时区耦合。

**数据模型与关系**：

```
User (1) ──< ChatSession (1) ──< ChatMessage
GuestUsage  (与 User 无关联，独立按 identity+date 计数)
```

- `users`：`username`（唯一）、`password_hash`。
- `chat_sessions`：`user_id` FK（`ondelete=CASCADE`）、`title`，`created_at`/`updated_at` 由数据库 `func.now()` 维护。
- `chat_messages`：`session_id` FK（`ondelete=CASCADE`）、`role`（user/assistant）、`content`（Text）。
- 会话/消息删除通过 ORM `cascade="all, delete-orphan"` 级联清理。
- 当前为开发期自动建表（`Base.metadata.create_all`），未引入 Alembic 迁移。

### 4.4 前端架构

```
frontend/
├── app/            # 路由页面（/、/login、/register、/chat、/settings）
├── components/     # UI 组件（ChatSidebar、MessageList、MessageBubble、CodeBlock、GuestLimitDialog 等）
├── store/          # Zustand 状态：useAuthStore / useChatStore / useSessionStore
├── lib/api/        # 后端接口封装：client（统一 fetch+鉴权头）、auth、sessions、chat
├── lib/utils/      # anonymousTrial（游客本地标识与计数）、groupSessionsByDate
└── types/          # auth/session/message 类型定义
```

- **鉴权头与游客标识统一构造**（`lib/api/client.ts`）：所有请求统一通过 `apiFetch` 发出；若本地存在 token 则附加 `Authorization: Bearer`，否则附加 `X-Anonymous-Id`；SSE 流式请求复用同一套 header 构造逻辑。
- **SSE 流式消费**（`lib/api/chat.ts` + `store/useChatStore.ts`）：手动按 `\n\n` 分隔 SSE 事件，兼容半条事件拼接；`sendMessage` 做乐观更新（先插入用户消息+占位 assistant 消息，再随 `onDelta` 增量追加最终回复，`onReasoning` 增量追加思维链到 `reasoning` 字段，由 `MessageBubble` 以可折叠的「💭 思考过程」区块展示）；支持 `AbortController` 中断流（"停止生成"），中断视为正常结束。
- **状态管理边界**：`useAuthStore`（当前用户/登录态）、`useSessionStore`（会话列表/当前选中）、`useChatStore`（消息内容/流式状态/游客限额提示/错误信息），未引入额外的全局状态库。

### 4.5 跨端协议约定

| 内容 | 约定 |
| --- | --- |
| 游客身份传递 | 请求头 `X-Anonymous-Id`（前端生成的本地匿名 ID） |
| 登录身份传递 | 请求头 `Authorization: Bearer <JWT>` |
| 对话流协议 | `POST /api/chat/stream`，响应 `text/event-stream`，每帧 `data: {json}\n\n` |
| SSE 事件类型 | `session` / `delta` / `reasoning` / `error` / `done` |

### 4.6 配置项（环境变量，`backend/.env`）

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | MySQL 连接串 | `mysql+pymysql://root:@127.0.0.1:3306/chat_llm?charset=utf8mb4` |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` | JWT 签发配置 | — / HS256 / 10080 分钟 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` | 第三方 LLM 接入 | — / `https://api.deepseek.com/v1` / `deepseek-reasoner`（思考模式） |
| `GUEST_DAILY_LIMIT` | 游客每日额度 | 5 |
| `CORS_ORIGINS` | 允许的前端来源（逗号分隔） | `http://localhost:3000` |

## 5. 关键业务规则

- 游客身份识别优先用 `anonymous_id`，IP 仅作兜底，避免误伤同网络下的多个用户
- 会话归属校验在 `session_service` 中统一处理，杜绝跨用户访问他人会话
- 开发环境启动时自动建表，生产环境建议改用 Alembic 迁移（当前未接入）

## 6. 已知架构缺口 / 待完善事项

- 无数据库迁移工具（Alembic），生产环境的 schema 变更需要手动管理
- 无限流/熔断/重试机制应对第三方 LLM 服务异常（仅做了错误转 SSE event，未做重试）
- 无自动化测试（未发现 `tests/` 目录）
- `GuestUsage` 表无过期清理机制，长期运行会持续累积历史行
- 暂未发现支付/订阅、多模型切换等商业化功能，如有规划需补充产品文档

测试结果详见 [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md)；产品/架构细节的完整版分别见 [`docs/产品文档.md`](docs/产品文档.md)、[`docs/技术架构文档.md`](docs/技术架构文档.md)。

## 7. 项目结构

```
backend/    # FastAPI 后端
frontend/   # Next.js 前端
docs/       # 产品文档、技术架构文档、测试报告
```

## 8. 常用命令

### 后端

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 前端

需要 Node 18.18+（本机默认 Node 版本过旧时，可临时 `export PATH=/usr/local/Cellar/node@20/20.20.2/bin:$PATH`）：

```bash
cd frontend
npm install
npm run dev      # 开发模式
npm run build    # 生产构建
npm run lint      # 代码检查
```

## 9. 开发规范

- 修改代码前先说明修改方案
- 不要一次性重构无关代码
- 新增功能时优先参考已有代码风格
- 修改公共方法时需要说明影响范围
- 涉及接口变更时需要同步更新文档
- 涉及数据库变更时需要说明迁移方案
- 不要修改无关模块
- 公共 API 变更前先说明影响范围
- 修复 Bug 时优先给最小修改方案

## 10. AI 回答偏好

- 先给思路，再给代码
- 涉及多个文件时，按文件列出改动
- 不确定时先说明风险，不要直接猜
- 优先做最小可行修改
