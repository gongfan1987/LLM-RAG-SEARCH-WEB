"""文本重排（rerank）：用交叉编码器对候选文档按与 query 的相关性重新打分排序。

为什么需要：Milvus 向量检索偏「召回」（语义相近就能命中），rerank 偏「精确」
（逐对判断 query 与文档的相关度）。先粗召回较多候选、再 rerank 取前几条，
能显著提升真正进入 LLM 上下文的片段质量。

默认对接 DashScope 的 gte-rerank（HTTP API，用 DashScope 凭证）。属纯技术封装、无 langchain，
故放 utils。未启用 / 未配置 / 调用失败时降级为「保持原顺序」，绝不影响主检索流程。
"""
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def rerank(query: str, documents: list[str], top_n: int) -> list[int]:
    """返回按相关性从高到低排序后的文档下标（最多 top_n 个）。

    未启用 / 未配置 / 文档为空 / 调用失败时，降级返回原顺序的前 top_n 个下标。
    """
    n = len(documents)
    fallback = list(range(min(top_n, n)))
    settings = get_settings()
    if not settings.rerank_configured or n == 0:
        return fallback

    payload = {
        "model": settings.rerank_model,
        "input": {"query": query, "documents": documents},
        "parameters": {"return_documents": False, "top_n": min(top_n, n)},
    }
    # 用 httpx.Timeout 显式约束 connect/read，避免冷启动下读阶段无限拖延。
    timeout = httpx.Timeout(settings.rerank_timeout, connect=5.0)
    try:
        response = httpx.post(
            settings.rerank_base_url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.effective_rerank_api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json()["output"]["results"]
        indices = [item["index"] for item in results if 0 <= item.get("index", -1) < n]
    except Exception as exc:  # noqa: BLE001 rerank 是增强项，任何失败都不能影响检索
        logger.warning("rerank 失败，保持向量检索原顺序: %s", exc)
        return fallback
    return indices[:top_n] or fallback
