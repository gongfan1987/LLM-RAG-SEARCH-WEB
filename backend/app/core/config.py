"""应用配置：统一从环境变量读取，不在代码中硬编码任何密钥。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # 数据库
    database_url: str = "mysql+pymysql://root:@127.0.0.1:3306/chat_llm?charset=utf8mb4"

    # JWT
    jwt_secret_key: str = ""
    jwt_algorithm: str = ""
    jwt_expire_minutes: int = 60 * 24 * 7

    # 第三方 LLM（OpenAI 兼容协议）
    # deepseek-v4-pro：支持 function calling（工具调用）+ 思考模式（thinking）。
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_name: str = ""
    # 思考模式：开启后通过 extra_body={"thinking": {"type": "enabled"}} 让模型先推理再作答，
    # 推理强度由 llm_reasoning_effort 控制（high/medium/low）。思维链经 reasoning_content
    # 落在 chunk.additional_kwargs，由 client 作为 ("reasoning", …) 事件产出，仅供前端展示。
    # 关闭（false）时不向 ChatOpenAI 传 reasoning_effort / extra_body，回退普通对话模式。
    llm_thinking_enabled: bool = False
    llm_reasoning_effort: str = ""

    # MySQL MCP 工具（默认关闭）
    # 开启后 LLM 可经 MCP server 对数据库执行 SQL。务必为其配置只读账号 / 独立库，
    # 不要直连存有密码哈希等敏感数据的主库。MCP server 以 stdio 子进程方式拉起，
    # 连接参数从 mysql_mcp_database_url（留空则回退 database_url）解析后通过环境变量传入
    # （见 app/llm/mcp.py）。
    mysql_mcp_enabled: bool = False
    mysql_mcp_command: str = ""
    mysql_mcp_args: str = ""  # 空格分隔，按需替换为你使用的 MySQL MCP server
    # MCP 专用连接串：建议指向只读账号 / 独立库，与主库解耦。留空则回退到 database_url。
    mysql_mcp_database_url: str = ""

    @property
    def effective_mcp_database_url(self) -> str:
        return self.mysql_mcp_database_url or self.database_url

    # Memory MCP 工具（知识图谱式持久记忆，默认关闭）：开启后 LLM 可经 MCP 跨会话存取记忆
    # （实体/关系/观察）。官方 server 为 Node 实现，需宿主有 npx/node。以 stdio 子进程拉起，
    # memory_mcp_file_path 指定记忆持久化文件（留空用 server 默认路径）。见 app/llm/mcp.py。
    memory_mcp_enabled: bool = False
    memory_mcp_command: str = "npx"
    memory_mcp_args: str = "-y @modelcontextprotocol/server-memory"  # 空格分隔
    memory_mcp_file_path: str = ""

    # 阿里云 OSS（对象存储）：用于存放 LLM 产出的图片/视频/文件等资源。
    # 凭证全部来自环境变量，代码中不硬编码。endpoint 形如
    # https://oss-cn-hangzhou.aliyuncs.com；oss_public_base_url 用于自定义域名/CDN，
    # 留空则由 endpoint + bucket 推导访问地址（见 app/utils/oss.py）。
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_public_base_url: str = ""

    @property
    def oss_configured(self) -> bool:
        return all(
            [self.oss_access_key_id, self.oss_access_key_secret, self.oss_endpoint, self.oss_bucket]
        )

    # 文本向量化（embedding）：默认对接 DashScope 兼容模式的 Qwen3-Embedding 模型
    # （text-embedding-v4 基于 Qwen3-Embedding），把文本转成向量供向量检索/RAG 使用。
    # OpenAI 兼容协议；base_url / model 也可改指向自托管的 Qwen3-Embedding 服务。
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model_name: str = "text-embedding-v4"
    # 单次向量化请求的最大文本条数。DashScope text-embedding-v4 限制每批 ≤20，
    # 默认取 10 较稳妥；批量 embed 时按此分批，避免超限报错。
    embedding_batch_size: int = 10
    # 单次 embedding 请求超时（秒）与重试次数：避免冷启动/限流时长时间死等，
    # 超时即快速失败 → RAG 降级为「无知识库」，不拖死对话。
    embedding_timeout: float = 15.0
    embedding_max_retries: int = 1

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_api_key and self.embedding_model_name)

    # Milvus 向量库：用于向量检索（RAG 等场景）。uri 形如 http://127.0.0.1:19530；
    # 本地无鉴权时 token 留空，托管服务（如 Zilliz Cloud）填对应 token。
    # 仅封装向量存取，不负责文本 embedding（见 app/utils/milvus.py）。
    milvus_uri: str = ""
    milvus_token: str = ""
    # 用户名/密码鉴权（如阿里云 / Zilliz 托管 Milvus）；本地无鉴权时留空。凭证走环境变量，勿硬编码。
    milvus_user: str = ""
    milvus_password: str = ""
    milvus_collection: str = ""  # 对话索引集合
    milvus_dim: int = 0  # 向量维度，建集合时使用；留 0 则自动按 embedding 实际输出维度推导
    # 知识库专用集合：与对话索引集合分开（id 空间与语义不同）。
    milvus_kb_collection: str = ""

    @property
    def milvus_configured(self) -> bool:
        return bool(self.milvus_uri and self.milvus_collection)

    @property
    def effective_milvus_token(self) -> str:
        """连接 Milvus 的 token：优先显式 token，否则由 用户名:密码 组装（托管 Milvus 鉴权方式）。"""
        if self.milvus_token:
            return self.milvus_token
        if self.milvus_user and self.milvus_password:
            return f"{self.milvus_user}:{self.milvus_password}"
        return ""

    # 知识库文档导入：切分参数（字符数）。
    kb_chunk_size: int = 0
    
    kb_chunk_overlap: int = 0

    # RAG 检索：最终拼进上下文 / 返回给模型的片段数。
    rag_top_k: int = 0
    # 启用 rerank 时，先从 Milvus 粗召回的候选数（再 rerank 取前 rag_top_k）。
    rag_recall_k: int = 0

    @property
    def kb_configured(self) -> bool:
        return bool(self.embedding_configured and self.milvus_uri and self.milvus_kb_collection)

    # PDF 复杂表格用多模态 VL 模型（Qwen-VL，DashScope）解析：把含表格的页面渲染成图片交给
    # 视觉模型转成 markdown 表，能更好还原合并表头等复杂结构。**默认关闭**（每个含表页面一次 VL
    # 调用，慢且耗 token）；只对 PDF、且只对检测到表格的页面生效。vl_api_key 留空复用 embedding_api_key。
    pdf_vl_enabled: bool = False
    vl_model: str = ""
    vl_api_key: str = ""
    vl_base_url: str = ""
    vl_timeout: float = 0.0

    @property
    def effective_vl_api_key(self) -> str:
        return self.vl_api_key or self.embedding_api_key

    @property
    def vl_configured(self) -> bool:
        return bool(self.pdf_vl_enabled and self.effective_vl_api_key and self.vl_model)

    # 重排（rerank）：对 Milvus 召回的候选用交叉编码器重新打分排序，提升进入上下文的片段质量。
    # 默认走 DashScope 的 gte-rerank（HTTP API）；未启用或调用失败时降级为保持向量检索原顺序。
    # rerank_api_key 留空则复用 embedding_api_key（同为 DashScope 凭证）。
    rerank_enabled: bool = False
    rerank_model: str = ""
    rerank_api_key: str = ""
    rerank_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    rerank_timeout: float = 0.0  # rerank 请求超时（秒）；超时降级为保持原顺序

    @property
    def effective_rerank_api_key(self) -> str:
        return self.rerank_api_key or self.embedding_api_key

    @property
    def rerank_configured(self) -> bool:
        return bool(self.rerank_enabled and self.effective_rerank_api_key and self.rerank_model)

    # 联网搜索工具（function calling）：web_search 走 DuckDuckGo（免费、无需 key）；
    # tavily_search 走 Tavily（需 key，返回带来源的合成答案）。两个工具都绑定给模型，由模型
    # 按问题类型自动选择调用哪个（见 app/llm/web_search.py）。tavily_api_key 留空则不注册
    # tavily_search，模型只看到 web_search。凭证走环境变量，勿硬编码。
    # web_search_enabled：联网搜索总开关，关闭后两个工具都不注册，模型无联网能力。
    web_search_enabled: bool = False
    tavily_api_key: str = ""
    tavily_base_url: str = ""
    web_search_max_results: int = 0  # 单次搜索返回的结果条数（两个工具共用）
    web_search_timeout: float = 0.0  # Tavily 请求超时（秒），超时即失败并回灌错误文本
    # web_search 抓正文：搜索结果的 body 只是页面简介，常不含明细（如赛程具体场次），
    # 导致模型「搜到对的页面却答不准」。开启后对前 web_search_fetch_count 篇结果抓取正文
    # （截断到 web_search_content_chars 字）喂给模型，显著提升准确度，代价是更慢、更耗 token。
    # 长页面（如整份赛程）按字数从头截断可能漏掉目标日期，这类问题更适合走 tavily_search。
    web_search_fetch_content: bool = False
    # 抓前 3 篇：很多页面开头是导航/菜单样板，只抓前 1-2 篇易错过内容丰富的那篇；
    # 抓 3 篇显著提升命中真实明细的概率（实测「世界杯赛程」类查询由 0 条场次提升到 20+ 条）。
    web_search_fetch_count: int = 0
    web_search_content_chars: int = 0

    @property
    def tavily_configured(self) -> bool:
        return bool(self.tavily_api_key)

    # 游客每日限额
    guest_daily_limit: int = 20

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
