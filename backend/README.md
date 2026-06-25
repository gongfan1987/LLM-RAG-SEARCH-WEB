# AI 对话应用后端

基于 FastAPI 实现，参考 DeepSeek 风格的对话产品。支持游客试用（限次）与登录用户（无限次/历史会话），流式 SSE 返回 AI 回复。

## 技术栈

- Web 框架：FastAPI + Uvicorn
- ORM：SQLAlchemy 2.x + PyMySQL（MySQL）
- 鉴权：JWT（python-jose） + bcrypt（passlib）密码哈希
- LLM 调用：langchain-openai（`ChatOpenAI`）对接第三方 OpenAI 兼容协议接口（如 DeepSeek 官方 API），支持流式输出与工具调用（内置 `get_current_date`）
- 外部工具：langchain-mcp-adapters + mcp，把 `mysql-mcp-server` 的查询工具（`execute_sql` 等）接入对话。`MYSQL_MCP_ENABLED` 默认关闭；开启步骤：①`MYSQL_MCP_ENABLED=true`，②`MYSQL_MCP_COMMAND=python` + `MYSQL_MCP_ARGS=-m mysql_mcp_server`（或装 uv 后用默认 `uvx`），③`MYSQL_MCP_DATABASE_URL` 指向只读账号（强烈建议，勿用主库 root）。接入 MCP 已将 fastapi/pydantic/starlette/uvicorn 升级到与 mcp 兼容版本，见 requirements.txt
- 对象存储：oss2（阿里云 OSS 官方 SDK），封装为 `app/utils/oss.py` 中的 `OssClient`。登录用户回复落库前，`app/services/resource_service.py` 会把回复中内联的 base64 图片/视频/文件转存到 OSS、替换为外链，避免历史消息膨胀。凭证全部来自环境变量（`OSS_*`，见 `.env.example`），`OSS_*` 全部留空即整体降级为 no-op（不启用）
- 向量库：pymilvus（Milvus 官方 SDK），封装为 `app/utils/milvus.py` 中的 `MilvusStore`，提供集合管理与向量插入/检索（仅处理向量，不负责 embedding）。登录用户每轮对话落库后，`app/services/conversation_index_service.py` 会把「用户提问 + AI 回复」向量化并自动索引进 Milvus；对话时 `app/services/rag_service.py` 按所选范围检索召回拼进上下文（RAG）。连接配置来自环境变量（`MILVUS_*`，见 `.env.example`），`MILVUS_URI` 与 `MILVUS_COLLECTION` 都填才算启用
- 文本向量化：Qwen3-Embedding（默认 DashScope 兼容模式的 `text-embedding-v4`，OpenAI 兼容协议；也可指向自托管服务），封装为 `app/llm/embedding.py` 中的 `EmbeddingClient`，把文本转成向量供 Milvus 检索/RAG 使用。配置来自环境变量（`EMBEDDING_*`，见 `.env.example`）
- 知识库（区分全局/个人，需登录，编排在 `app/services/knowledge_base_service.py`，独立集合 `MILVUS_KB_COLLECTION`）：
  - 一步导入 `POST /api/knowledge-base/documents`：multipart 上传 **.txt / .md / .pdf / .docx / .xlsx**（.doc/.xls 暂不支持）+ `scope`（`global` 全局共享 / `personal` 仅自己，默认 personal），经「解析（`app/services/document_parsing/`）→ 表格感知切分（`app/utils/text.py` 的 `split_markdown`，markdown 表格整体保留、超长表按行分块并重复表头）→ embedding → 写入 Milvus」入库。PDF 用 **pymupdf4llm** 转 Markdown（表格保留为 markdown 表，避免 `get_text` 揉烂与重复）；Word/Excel 表格也序列化为 markdown 表；图片提取后上传 OSS 并 OCR（`app/utils/ocr.py`），以「图片链接 + 图中文字」文本块入库。**复杂表格（合并表头等）可选开启多模态 VL（`PDF_VL_ENABLED=true`，Qwen-VL via DashScope，`app/llm/vl.py`）**：仅对 PDF 中检测到表格的页面渲染成图片交视觉模型转 markdown，更好还原结构；默认关闭（每个含表页面一次 VL 调用，慢且耗 token），VL 失败时自动回退文本提取
  - 预览 `POST /api/knowledge-base/documents/preview`：解析+切分后返回 chunk 列表（**不写入 Milvus**，图片在此阶段已转存 OSS+OCR），供前端逐段预览/编辑微调
  - 提交 `POST /api/knowledge-base/documents/commit`：把（可能已编辑的）chunk 列表向量化写入；用于「预览后确认导入」与「已入库文档编辑后覆盖」（按 doc_id 删旧写新，幂等；覆盖校验归属）
  - 查看切片 `GET /api/knowledge-base/documents/{doc_id}/chunks`：返回某已入库文档的全部分片（按序），供再次预览/编辑
  - 列出 `GET /api/knowledge-base/documents`：当前用户可见文档（全部 global + 自己的 personal），聚合统计分片数
  - 删除 `DELETE /api/knowledge-base/documents/{doc_id}`：仅上传者本人可删，不存在→404 / 非本人→403
  - 配齐 `EMBEDDING_*` + `MILVUS_URI` + `MILVUS_KB_COLLECTION` 即启用
- RAG 检索增强（`app/services/rag_service.py`）：以 **LLM 工具（function calling）** 形式接入——按请求 `kb_scope` + 用户构造 `search_knowledge_base` 工具注入对话，模型在需要时自行调用，从知识库召回相关片段。检索范围由请求体 `kb_scope` 控制：`none`/`global`/`personal`/`both`（默认 `both`，游客退化为仅全局；`none` 或无可检索范围则不挂工具）。检索为增强项，未配置或失败时自动降级，不影响回复
- 重排（rerank，`app/utils/rerank.py`，可选，默认关闭）：启用后（`RERANK_ENABLED=true`）先从 Milvus 粗召回 `RAG_RECALL_K` 条候选，再用交叉编码器（默认 DashScope `gte-rerank-v2`）重排，取前 `RAG_TOP_K` 进上下文，提升片段相关性。未启用/调用失败时降级为保持向量检索原顺序

## 目录结构

```
backend/
├── app/
│   ├── main.py          # 应用入口，挂载中间件与路由
│   ├── core/            # 配置（config.py）、JWT与密码哈希（security.py）、依赖注入（deps.py）
│   ├── db/              # 数据库引擎与 Base（base.py）
│   ├── models/          # ORM 模型：user / chat_session / chat_message / guest_usage
│   ├── schemas/         # Pydantic 请求/响应模型
│   ├── llm/             # LLM 组件：封装 langchain（client / tools / mcp / embedding），对外暴露 stream_reply、LlmCallError、load_mcp_tools、EmbeddingClient
│   ├── services/        # 业务逻辑层：auth / session / message / chat / guest_quota / knowledge_base / rag / document_parsing（多格式解析）
│   ├── routers/         # 路由层：仅做参数解析与调用 service，不直接操作 ORM/写 SQL
│   └── utils/           # 技术辅助：time、oss、milvus、text（切分）、ocr（图片识别）、rerank（重排），不含业务规则
├── requirements.txt
└── .env.example
```

分层原则：routers 不直接操作数据库，统一通过 services 调用；utils 只放无业务含义的工具函数；业务规则（游客限额、会话归属校验等）集中在 services 层，便于复用和测试。

## 快速开始

1. 创建并激活虚拟环境

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

> 其中 `rapidocr-onnxruntime`（图片 OCR）较重，首次使用会下载 onnx 模型。若暂不需要识别文档中图片的文字，可不安装它——`app/utils/ocr.py` 会自动降级为「不识别图中文字」，图片仍会上传 OSS 并以链接入库，不影响其余功能。

3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 MySQL 连接串、JWT 密钥、LLM_API_KEY 等
```

4. 确保 MySQL 中已创建好对应数据库（如 `ai_chat`），应用启动时会自动建表（开发环境便捷方案，生产建议改用 Alembic 迁移）：

```sql
CREATE DATABASE ai_chat CHARACTER SET utf8mb4;
```

5. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

6. 访问接口文档：http://localhost:8000/docs

## 测试

测试基于 **pytest + pytest-asyncio**，用例位于 `backend/tests/`，目前覆盖 `app/llm` 组件（LLM 客户端、本地工具、MCP、Qwen3-Embedding）、`app/utils`（oss / milvus / text / ocr / rerank）、`app/services`（resource / conversation_index / knowledge_base / rag）与 `app/services/document_parsing`（txt/md/pdf/docx/xlsx 解析、表格序列化）。

### 运行

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt   # 首次：装运行时依赖 + pytest/pytest-asyncio
pytest                                 # 跑全部用例
pytest -v                              # 显示每个用例名（中文，能看出业务场景）
pytest tests/test_llm_client.py        # 只跑单个文件
pytest -k tool                         # 按关键字筛选用例
```

预期结果：`136 passed, 2 skipped`（跳过的是 2 个默认关闭的端到端用例，见下）。

### 可选端到端（e2e）测试

`tests/test_e2e_rag.py` 是**默认跳过**的真实链路用例（2 个）：① 上传文档 → 提问 → 验证模型主动触发 `search_knowledge_base` 工具并据知识库回答（需 embedding + LLM）；② 预览 → 编辑某段 → 提交入库 → 查回分片，验证编辑真实生效（仅需 embedding + Milvus Lite）。它们会发起真实外部调用，消耗 token，故默认不跑。

```bash
RUN_E2E=1 pytest tests/test_e2e_rag.py -s
```

前置：`.env` 配好 `EMBEDDING_*` 与 `LLM_API_KEY`；**无需**启动 Milvus 服务端——用 Milvus Lite 本地文件（`pip install -r requirements-dev.txt` 已含 `milvus-lite`）。缺配置或缺 `milvus-lite` 时该用例自动 skip。

### 约定与原则

- **不依赖真实外部服务**：测试用 `tests/fakes.py` 里的替身（`FakeLLM` / `FakeChunk` / `FakeTool` / 伪 MCP 客户端）替代真实 LLM、数据库、网络；不会发起真实 API 调用，也不会连 MySQL。
- **配置隔离**：通过 `monkeypatch` 改写 `settings` 属性（如 `llm_api_key`、`mysql_mcp_enabled`），不依赖本地 `.env`。
- **覆盖正常 + 异常**：例如 `stream_reply` 既测无工具调用的流式产出、工具调用闭环，也测未配置 key 报错、达到最大轮数停止、底层异常包装为 `LlmCallError`。
- **用例命名用中文表达业务场景**，例如 `test_模型请求工具后执行并在下一轮给出最终回复`。
- 配置见 `pytest.ini`（`asyncio_mode = auto`，async 用例无需逐个加标记；`testpaths = tests`）。

### 新增测试

在 `backend/tests/` 下新建 `test_*.py`；需要替身时复用或扩展 `tests/fakes.py`；涉及真实 LLM/DB/网络的依赖一律用 mock 或替身替换，保持测试可离线、可重复运行。

## 关于游客模式

未携带有效 JWT 的请求视为游客模式，后端根据请求体中的 `anonymous_id`（前端生成并持久化的匿名标识，优先）或客户端 IP（兜底）按天计数，超过 `GUEST_DAILY_LIMIT`（默认 5 次）后返回 429。游客模式不保存会话历史。

登录用户携带 JWT 后不受次数限制，且对话历史会保存到 `chat_sessions` / `chat_messages` 表中。
