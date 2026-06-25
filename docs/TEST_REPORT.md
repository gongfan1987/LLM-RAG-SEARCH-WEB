# AI对话应用 测试报告

测试对象：`backend/`（FastAPI + MySQL + JWT + SSE）与 `frontend/`（Next.js + TypeScript + Tailwind + Zustand）
测试日期：2026-06-22

---

## 一、测试阶段概览

| 阶段 | 内容 | 结果 |
|---|---|---|
| 第一轮：构建后初测 | 依赖安装、本地启动、接口连通性、前后端联调 | 发现3个阻断性问题 + 2个功能性问题 |
| 修复 | 针对发现的问题逐一修复 | 全部修复并复测通过 |
| 第二轮：真实环境验证 | 真实MySQL（127.0.0.1:3306/chat_llm）+ 真实DeepSeek API Key | 端到端验证通过 |
| 运行期问题 | `uvicorn --reload` 启动报错 | 定位为端口残留进程，非代码问题，已解决 |

---

## 二、第一轮测试结果（构建后初测）

### 构建/启动结果

| 项目 | 结果 | 说明 |
|---|---|---|
| 后端依赖安装 | 通过 | `backend/.venv`，Python 3.12，requirements.txt 全部安装成功 |
| 后端启动（uvicorn+sqlite替代验证） | 通过（需先修复bcrypt版本） | 路由全部注册成功（`/api/auth/*`、`/api/sessions*`、`/api/chat/stream`、`/health`） |
| 前端 `npm install`/`npm run build` | 通过 | 需 Node 20（系统默认 Node 14 过旧），TypeScript检查通过，5个页面全部静态预渲染成功 |
| 前端 `npm run start` | 通过 | 使用3001端口（本机3000被Docker占用） |

### 接口测试结果

| 测试项 | 结果 |
|---|---|
| 注册接口（含重复用户名400校验） | 通过 |
| 登录接口（含错误密码401） | 通过 |
| GET /api/auth/me（带/不带token） | 通过 |
| 新建会话 POST /api/sessions | 通过 |
| 会话列表 GET /api/sessions | 通过 |
| 访问不存在会话返回404 | 通过 |
| CORS（Origin=http://localhost:3000） | 通过 |
| 前端路由探活（/, /chat, /login, /register, /settings） | 通过 |
| 游客限额逻辑（5次/天） | 逻辑正确，但HTTP状态码未能正确返回（见问题2） |
| chat/stream 无LLM Key时的错误处理 | **失败**（见问题2） |
| 自动化测试套件 | 无（项目未包含测试文件） |

### 发现的问题

**1.（阻断）bcrypt 与 passlib 版本不兼容，导致注册/登录 500**
`backend/requirements.txt` 锁定 `passlib[bcrypt]==1.7.4`，未锁定 `bcrypt` 版本，pip默认装到 `bcrypt 5.0.0`。passlib 1.7.4 的后端自检逻辑（`detect_wrap_bug`）触发 `ValueError: password cannot be longer than 72 bytes`，导致注册、登录100%返回500。

**2.（阻断）chat/stream 流式接口遇到错误时连接异常中断**
位置：`backend/app/services/chat_service.py`、`backend/app/routers/chat.py`。
`StreamingResponse` 已发出200状态行后，generator内部再 `raise HTTPException` 无法被FastAPI转换为4xx响应，导致连接异常终止，客户端收不到任何错误信息。实测登录用户在无LLM Key时调用接口，流中只有 `session` 事件后连接中断；游客第6次请求（超出5次限额）同样是200后连接中断，而非预期的429。前端 `frontend/lib/api/chat.ts` 已预留处理 `event.error` 的逻辑，说明设计意图是后端应yield错误事件，但实现缺失。

**3.（阻断）前后端auth接口字段契约完全不一致**
- 字段名：后端要求 `username`，前端用 `account`
- 响应结构：后端登录返回 `{access_token, token_type}`，前端期望 `{token, user}`
- 注册响应：后端只返回 `UserResponse`（无token），前端期望能直接拿到token
- `/api/auth/me`：后端返回扁平结构，前端期望 `{user: User}` 包装
- `id`类型：后端 `int`，前端 `string`
以上不一致会导致真实浏览器中注册、登录、刷新后恢复登录态全部失败。

**4.（功能性）游客匿名标识传递方式不一致**
前端通过请求头 `X-Anonymous-Id` 传递，后端却只从请求体 `anonymous_id` 字段读取（且前端请求体中实际未携带该字段），导致游客限额回退为按IP计算，与"按浏览器区分游客"的设计意图不符。

**5.（阻断）session_id 类型不一致**
后端 `session_id: int | None`，前端 `session_id?: string`，类型不匹配会触发Pydantic 422。

**6.（建议项）环境配置示例缺失**：`.env.example` 当时尚未补充完整。

**7.（环境限制，非代码问题）**：本机3000端口被Docker占用，改用3001验证；当时本机无可用MySQL实例，用SQLite替代验证了基本CRUD链路；未配置真实LLM Key，仅验证"无Key路径"。

---

## 三、修复内容

| 问题 | 修复方式 |
|---|---|
| bcrypt版本冲突 | `backend/requirements.txt` 固定 `bcrypt==4.0.1` |
| chat/stream异常中断 | `chat_service.py` 内所有 `raise HTTPException` 改为 `yield {"type":"error","error":...}` 后 `return`，覆盖LLM Key缺失、LLM调用失败、会话归属校验失败、游客身份缺失、游客超额等场景；路由层不再处理这些错误，仅转发生成器 |
| auth字段契约不一致 | 统一为：请求字段用 `username`；登录/注册响应统一为 `{access_token, token_type, user}`（注册接口复用登录响应结构，避免前端注册后再调一次登录）；`/me` 维持扁平结构，前端去除 `.user` 包装；`id` 统一为 `number` |
| 游客匿名标识传递方式不一致 | 后端新增 `get_anonymous_id` 依赖，从请求头 `X-Anonymous-Id` 读取；`ChatStreamRequest` 删除冗余的 `anonymous_id` 字段 |
| session_id类型不一致 | 前端 `ChatStreamPayload.session_id`、`ChatSession.id` 及相关store方法签名统一改为 `number` |
| 额外发现：SSE字段名不匹配 | 后端帧为 `{"type":"delta","content":...}`，前端原代码读取 `event.delta`，永远读不到增量内容；统一为 `{type, content, session_id, error}` 并修正前端解析逻辑 |

### 修复后复测结果
1. bcrypt 4.0.1 生效，注册/登录/`/me` 均返回200，字段符合新契约
2. chat/stream 在无LLM Key时返回 `HTTP 200` + SSE `{"type":"error",...}` 帧，连接正常结束（非中断）；游客连续请求6次，第6次正确返回超额error事件，且两个不同匿名id各自独立计数
3. 前端 `npm run build`（Node 20）编译通过，TypeScript检查无误
4. 端到端联调：register → login → create session（数字id）→ chat/stream携带数字session_id → 先收到session事件再收到error（因当时无LLM Key），链路完整可用
5. 测试结束后已清理所有手动启动的进程，无残留

---

## 四、第二轮测试：真实环境验证

配置变更：
- `DATABASE_URL` 改为 `mysql+pymysql://root:@127.0.0.1:3306/chat_llm?charset=utf8mb4`（真实MySQL实例，非SQLite替代）
- `LLM_API_KEY` 填入真实DeepSeek密钥（值已写入 `backend/.env`，该文件已加入 `.gitignore`，不会被提交）

### 验证步骤与结果

| 步骤 | 结果 |
|---|---|
| MySQL连通性检查（`SHOW DATABASES LIKE 'chat_llm'`） | 通过，`chat_llm` 数据库已存在 |
| SQLAlchemy `Base.metadata.create_all` 建表 | 通过，生成 `users`、`chat_sessions`、`chat_messages`、`guest_usages` 四张表 |
| 后端启动（真实MySQL+真实API Key） | 通过，`/health` 返回 `{"status":"ok"}` |
| 真实注册接口 | 通过，返回 `access_token` + `user`（写入真实MySQL） |
| 真实chat/stream调用（带JWT，消息："用一句话介绍你自己"） | **通过**，收到完整SSE流：`session`事件 → 13个`delta`事件（真实DeepSeek模型回复）→ `done`事件，无报错、无中断 |
| 测试数据清理 | 通过，已删除测试用户及对应会话/消息记录，进程已kill |

此轮验证证明：MySQL持久化、JWT鉴权、SSE流式传输、第三方LLM真实调用四个环节在真实配置下完整打通。

---

## 五、运行期问题：`uvicorn --reload` 报错

**现象**：用户执行 `uvicorn app.main:app --reload` 报错 `[Errno 48] Address already in use`。

**原因**：非代码缺陷，是第二轮验证测试中手动后台启动的旧uvicorn进程（PID 6010）未被正确清理，持续占用8000端口。

**处理**：通过 `lsof -i :8000` 定位到残留进程并 `kill`，确认端口释放后问题解决。

**建议**：后续本地反复重启调试时，可用 `lsof -i :8000` 先确认端口空闲，或固定用 `pkill -f "uvicorn app.main:app"` 清理残留进程，避免地址冲突。

---

## 六、当前已知限制

1. 项目目前没有自动化测试套件（无pytest/jest等测试文件），所有验证均为手工/脚本化的接口级测试，建议后续补充单元测试和集成测试（覆盖auth、会话CRUD、游客限额、SSE错误路径）。
2. 真实LLM对话内容仅做了基础连通性验证（一句话问候），未做长上下文、多轮对话、内容安全过滤等场景的压力测试。
3. CORS当前配置为 `http://localhost:3000,http://localhost:3001`，生产部署前需替换为真实域名。
4. 前端登录态目前存储在localStorage（非httpOnly Cookie），代码注释中已说明此安全权衡，如有更高安全要求建议后续迁移。

---

## 七、结论

经过两轮测试与一轮修复，核心链路（注册、登录、JWT鉴权、会话管理、SSE流式对话、游客限额、真实MySQL持久化、真实DeepSeek模型调用）均已验证可用。当前版本可用于本地开发与功能演示，正式上线前建议补充自动化测试与安全加固（见"已知限制"）。
