"""RAG 检索：把用户问题向量化，从知识库 Milvus 集合召回相关片段，拼成上下文块。

编排 EmbeddingClient（app.llm，问题→向量）与 MilvusStore（app.utils，知识库集合检索）。
决定检索范围（scope）、召回条数（rag_top_k）与上下文块的拼接格式。

可选范围（scope，由调用方按请求传入）：
- none     ：关闭检索
- global   ：仅全局库
- personal ：仅本人个人库（游客无个人库 → 无结果）
- both     ：全局 + 本人个人（默认；游客退化为仅全局）

降级原则：检索是回答质量的增强项，不是必需。知识库未配置、集合不存在或任一步失败时
返回空（仅记日志），绝不影响主对话流程。
"""
import logging

from app.core.config import get_settings
from app.llm import build_tool, get_embedding_client
from app.utils.milvus import get_kb_milvus_client
from app.utils.rerank import rerank

logger = logging.getLogger(__name__)

_KB_TOOL_DESCRIPTION = (
    "检索当前用户可见的知识库（已上传的文档/资料，含其中的表格与图片文字）。"
    "当用户的问题可能涉及这些已上传内容时，传入要查询的问题或关键词调用本工具，"
    "返回最相关的若干片段；若无相关内容会明确告知。"
)


def warmup() -> None:
    """预热 embedding / rerank 远程服务，把冷启动延迟（首次可达上百秒）挪到启动阶段，
    让用户首条请求不再踩冷启动。best-effort：未配置或失败都静默跳过，绝不影响启动。"""
    settings = get_settings()
    if settings.embedding_configured:
        try:
            get_embedding_client().embed_query("warmup")
        except Exception as exc:  # noqa: BLE001 预热失败无所谓
            logger.warning("embedding 预热失败（忽略）: %s", exc)
    if settings.rerank_configured:
        try:
            rerank("warmup", ["warmup document"], top_n=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank 预热失败（忽略）: %s", exc)


def _scope_filter(scope: str, user_id: int | None) -> str | None:
    """把检索范围转成 Milvus 过滤表达式；返回 None 表示无需/无法检索。"""
    if scope == "global":
        return 'scope == "global"'
    if scope in ("personal", "both"):
        if user_id is None:
            # 游客无个人库：personal 无可检索；both 退化为仅全局。
            return 'scope == "global"' if scope == "both" else None
        if scope == "personal":
            return f'owner_id == {user_id} and scope == "personal"'
        return f'scope == "global" or owner_id == {user_id}'
    return None  # none 或未知范围 → 跳过检索


def retrieve_context(query: str, user_id: int | None, scope: str) -> list[dict]:
    """召回与 query 最相关的知识库片段，返回 [{text, filename, scope}]；不可用/失败时返回 []。

    启用 rerank 时：先从 Milvus 粗召回 rag_recall_k 条候选，再用交叉编码器重排，取前 rag_top_k；
    未启用时：直接取向量检索的前 rag_top_k。
    """
    settings = get_settings()
    if not settings.kb_configured or not query.strip():
        return []
    expr = _scope_filter(scope, user_id)
    if expr is None:
        return []
    # 启用 rerank 时多召回一些候选，给重排留出筛选空间。
    recall_k = settings.rag_recall_k if settings.rerank_configured else settings.rag_top_k
    try:
        store = get_kb_milvus_client()
        if not store.collection_exists():
            return []
        vector = get_embedding_client().embed_query(query)
        hits = store.search(
            vector,
            limit=recall_k,
            output_fields=["text", "filename", "scope"],
            expr=expr,
        )
    except Exception as exc:  # noqa: BLE001 检索是增强项，任何失败都不能影响回复
        logger.warning("RAG 检索失败，已跳过: %s", exc)
        return []

    passages = [_to_passage(hit) for hit in hits]
    if settings.rerank_configured and len(passages) > 1:
        # rerank 内部失败会降级为原顺序的前 top_n，故此处无需再 try。
        order = rerank(query, [p["text"] for p in passages], settings.rag_top_k)
        return [passages[i] for i in order]
    return passages[: settings.rag_top_k]


def make_kb_search_tool(user_id: int | None, scope: str):
    """按请求构造一个绑定了 user_id/检索范围的「知识库检索」LLM 工具。

    返回 None 表示当前请求无需挂该工具：知识库未配置，或范围不可检索
    （scope=none、或游客选 personal——无个人库）。这样模型不会做无谓的工具调用。
    工具内部复用 retrieve_context（检索）+ build_context_block（拼接），仅在模型调用时执行。
    """
    settings = get_settings()
    if not settings.kb_configured or _scope_filter(scope, user_id) is None:
        return None

    def search_knowledge_base(query: str) -> str:
        """检索知识库并返回相关片段文本。"""
        passages = retrieve_context(query, user_id, scope)
        return build_context_block(passages) or "知识库中未找到与该问题相关的内容。"

    return build_tool("search_knowledge_base", _KB_TOOL_DESCRIPTION, search_knowledge_base)


def _to_passage(hit: dict) -> dict:
    """把 Milvus 命中（字段可能在 entity 下）规整为 {text, filename, scope}。"""
    entity = hit.get("entity", hit)
    return {
        "text": entity.get("text", ""),
        "filename": entity.get("filename", ""),
        "scope": entity.get("scope", ""),
    }

#在项目中做记忆层设计，全局共享状态ResearchState，设计全局共享状态机制，统一维护研究大纲。假设，事实，数据点，图标，草稿，终稿，评审反馈字段，实现跨Agent只是持续积累和状态传递。设计上下文Memory模块，记录用户历史问题，研究偏好和任务轨迹，增强多轮任务连贯与个性化交互体验。
def build_context_block(passages: list[dict]) -> str | None:
    """把召回片段拼成一段 system 上下文文本；无片段时返回 None。"""
    lines = []
    for i, passage in enumerate(passages, 1):
        text = passage.get("text", "").strip()
        if not text:
            continue
        source = passage.get("filename") or "知识库"
        lines.append(f"[{i}] (来源: {source})\n{text}")
    if not lines:
        return None
    body = "\n\n".join(lines)
    return (
        "以下是从知识库检索到的可能相关内容，回答时可参考；若与问题无关请忽略，"
        "不要编造未提供的信息：\n\n" + body
    )
