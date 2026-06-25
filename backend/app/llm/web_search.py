"""联网搜索工具：DuckDuckGo（免费、无需 key）+ Tavily（需 key，带 AI 合成答案）。

设计：两个工具都以本地工具形式绑定给模型，由模型按问题类型「自动切换」调用哪个——
docstring 已写明各自适用场景（快速查证用 web_search，复杂/研究型问题用 tavily_search）。
无需额外路由代码，function calling 本身即按 docstring 选择工具。

依赖边界：DuckDuckGo 走 ddgs 库；Tavily 复用项目已有的 httpx，不额外引入 SDK。
凭证从配置读取（tavily_api_key），代码中不硬编码。Tavily 未配置 key 时不注册其工具
（见 build_web_search_tools），模型只会看到 web_search。
"""
import httpx
from ddgs import DDGS
from langchain_core.tools import BaseTool, tool

from app.core.config import get_settings


def _fetch_content(client: DDGS, url: str, max_chars: int) -> str:
    """抓取网页正文并截断到预算字数。

    搜索结果的 body 只是页面简介，往往不含真正的明细（如赛程的具体场次时间），
    导致模型「搜到了对的页面却答不准」。这里用 ddgs 的 extract 拉取正文喂给模型。
    单页抓取失败（反爬/超时等）返回空串，调用方据此跳过，仅保留摘要，不中断整次搜索。
    """
    try:
        data = client.extract(url)
    except Exception:
        return ""
    text = str(data.get("content") or data.get("text") or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


@tool
def web_search(query: str) -> str:
    """免费联网搜索（DuckDuckGo），返回若干网页的标题、链接、摘要及前若干篇的正文摘录。

    适用于：快速查证事实、查找网页/官网链接、获取实时信息（新闻、价格、版本号等）。
    注意：正文摘录是从页面开头截取的，对「某个具体日期/时间的明细」（如赛程开赛时间、
    某天的航班/节目表）可能截不到目标段落——这类查询请改用 tavily_search。
    """
    settings = get_settings()
    client = DDGS()
    try:
        results = list(client.text(query, max_results=settings.web_search_max_results))
    except Exception as exc:  # 限流/网络等异常转为文本回灌，不中断对话
        return f"DuckDuckGo 搜索失败: {exc}"
    if not results:
        return "未找到相关结果。"

    # 对前 fetch_count 篇结果抓取正文（开关关闭则为 0），其余只给摘要，平衡准确度与耗时/token。
    fetch_count = settings.web_search_fetch_count if settings.web_search_fetch_content else 0
    blocks = []
    for i, r in enumerate(results, 1):
        block = f"{i}. {r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')}"
        if i <= fetch_count:
            content = _fetch_content(client, r.get("href", ""), settings.web_search_content_chars)
            if content:
                block += f"\n正文摘录：\n{content}"
        blocks.append(block)
    return "\n\n".join(blocks)


@tool
def fetch_url(url: str) -> str:
    """读取指定网页的正文内容（转为文本）。

    适用于：用户直接给了一个网址要你阅读/总结，或 web_search 搜到结果后需要进入某个链接看明细。
    与 web_search 配合：先搜索拿到链接，再用本工具读取目标页面的完整内容。
    """
    settings = get_settings()
    content = _fetch_content(DDGS(), url, settings.web_search_content_chars)
    return content or f"未能读取网页内容: {url}（可能被反爬拦截或页面为空）"


def _format_tavily(data: dict) -> str:
    """把 Tavily 响应整理为「合成答案 + 来源列表」文本。"""
    parts = []
    answer = data.get("answer")
    if answer:
        parts.append(f"综合答案：{answer}")
    sources = []
    for i, r in enumerate(data.get("results", []), 1):
        sources.append(f"{i}. {r.get('title', '')}\n{r.get('url', '')}\n{r.get('content', '')}")
    if sources:
        parts.append("来源：\n" + "\n\n".join(sources))
    return "\n\n".join(parts) or "未找到相关结果。"


@tool
def tavily_search(query: str) -> str:
    """高质量联网搜索（Tavily），服务端按相关性提取网页正文并综合出带来源的答案。

    优先用于：查询某个具体日期/时间的明细（如赛程开赛时间、某天安排）、复杂/研究型问题、
    需要把多个来源归纳成结论、对答案准确度与可引用来源要求较高的场景。
    只是快速查个事实或找链接时，用更轻量的 web_search 即可。
    查询「明天/今天」等相对时间的信息时，请先换算成具体日期再放进 query。
    """
    settings = get_settings()
    try:
        resp = httpx.post(
            f"{settings.tavily_base_url}/search",
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            json={
                "query": query,
                "max_results": settings.web_search_max_results,
                "include_answer": True,
                # advanced：服务端按相关性深度提取正文，对赛程/具体日期等明细更准（每次多耗 Tavily 额度）。
                "search_depth": "advanced",
            },
            timeout=settings.web_search_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # 调用失败转为文本回灌，不中断对话
        return f"Tavily 搜索失败: {exc}"
    return _format_tavily(data)


def build_web_search_tools() -> list[BaseTool]:
    """构造联网搜索工具列表，受总开关 web_search_enabled 控制。

    - 总开关关闭（WEB_SEARCH_ENABLED=false）：返回空列表，两个工具都不绑定给模型。
    - 开启：web_search 始终可用；tavily_search 仅在配置了 Tavily key 时启用——
      与 MCP / embedding 等组件「未配置即降级」的风格一致，避免模型调用注定失败的工具。
    """
    settings = get_settings()
    if not settings.web_search_enabled:
        return []
    # web_search + fetch_url 始终随总开关启用；tavily_search 仅在配置了 Tavily key 时追加。
    tools: list[BaseTool] = [web_search, fetch_url]
    if settings.tavily_configured:
        tools.append(tavily_search)
    return tools
