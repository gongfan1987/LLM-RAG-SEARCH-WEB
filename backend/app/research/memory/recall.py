"""任务轨迹的语义召回：把归档摘要向量化入 Milvus，新任务按主题语义召回相关历史。

复用 embedding + Milvus 基建，降级原则照搬 conversation_index_service / rag_service：
未配置或任一步失败 → 返回空 / 静默跳过，仅记日志，绝不阻断研究任务。
"""
import logging

from app.core.config import get_settings
from app.llm import get_embedding_client
from app.utils.milvus import get_trajectory_milvus_client

logger = logging.getLogger(__name__)

_collection_ready = False


def index_trajectory(trajectory_id: int, user_id: int | None, topic: str, summary: str) -> None:
    """把轨迹摘要向量化写入 Milvus（best-effort）。"""
    settings = get_settings()
    if not (settings.milvus_configured and settings.embedding_configured) or user_id is None:
        return
    try:
        vector = get_embedding_client().embed_query(summary)
        store = get_trajectory_milvus_client()
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
        store = get_trajectory_milvus_client()
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
