"""app/llm/web_search.py 单测：DuckDuckGo（免费）+ Tavily（需 key）两个联网搜索工具。

mock 说明：DDGS / httpx.post 用替身替换——不发真实请求；get_settings 用伪 settings 控制
Tavily 开关与结果条数。两个工具均不触达真实搜索服务（遵循「测试不依赖真实外部服务」）。
"""
import app.llm.web_search as ws


def _settings(
    tavily_key="",
    max_results=3,
    timeout=15.0,
    enabled=True,
    fetch_content=True,
    fetch_count=2,
    content_chars=200,
):
    return type(
        "S",
        (),
        {
            "web_search_enabled": enabled,
            "tavily_configured": bool(tavily_key),
            "tavily_api_key": tavily_key,
            "tavily_base_url": "http://tavily.local",
            "web_search_max_results": max_results,
            "web_search_timeout": timeout,
            "web_search_fetch_content": fetch_content,
            "web_search_fetch_count": fetch_count,
            "web_search_content_chars": content_chars,
        },
    )()


class _FakeDDGS:
    """替身 DDGS：text() 返回预置结果或抛错；extract() 返回预置正文或抛错。"""

    def __init__(self):
        self.results: list[dict] = []
        self.error: Exception | None = None
        self.contents: dict[str, str] = {}  # url -> 正文
        self.extract_error_urls: set[str] = set()
        self.extract_calls: list[str] = []

    def text(self, query, max_results=None):
        if self.error:
            raise self.error
        return self.results[:max_results] if max_results else self.results

    def extract(self, url, fmt="text_markdown"):
        self.extract_calls.append(url)
        if url in self.extract_error_urls:
            raise RuntimeError("抓取失败")
        return {"content": self.contents.get(url, "")}


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


# ---------- DuckDuckGo（web_search） ----------


def test_duckduckgo把结果格式化为标题链接与摘要(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings())
    fake = _FakeDDGS()
    fake.results = [
        {"title": "Python 官网", "href": "https://python.org", "body": "Python 编程语言"},
        {"title": "PyPI", "href": "https://pypi.org", "body": "包索引"},
    ]
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "python"})
    assert "Python 官网" in out and "https://python.org" in out and "Python 编程语言" in out
    assert "PyPI" in out and "https://pypi.org" in out


def test_duckduckgo按配置条数截断(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(max_results=1))
    fake = _FakeDDGS()
    fake.results = [
        {"title": "一", "href": "https://1", "body": "x"},
        {"title": "二", "href": "https://2", "body": "y"},
    ]
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "q"})
    assert "一" in out and "二" not in out


def test_duckduckgo无结果时返回提示(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings())
    fake = _FakeDDGS()
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "asdfzxcvqwer"})
    assert "未找到" in out


def test_duckduckgo调用异常时返回错误文本而不抛出(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings())
    fake = _FakeDDGS()
    fake.error = RuntimeError("被限流")
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "python"})
    assert "失败" in out and "被限流" in out


# ---------- DuckDuckGo 抓取正文（解决「只给摘要不给正文」导致的不准） ----------


def test_web_search抓取前N个结果的正文并附加(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(fetch_count=1, content_chars=1000))
    fake = _FakeDDGS()
    fake.results = [{"title": "赛程", "href": "https://wc/s", "body": "赛程页"}]
    fake.contents = {"https://wc/s": "06月26日 03:00 阿根廷 vs 巴西"}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "明天世界杯"})
    assert "06月26日 03:00 阿根廷 vs 巴西" in out
    assert fake.extract_calls == ["https://wc/s"]


def test_web_search正文按预算截断(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(fetch_count=1, content_chars=10))
    fake = _FakeDDGS()
    fake.results = [{"title": "t", "href": "https://u", "body": "b"}]
    fake.contents = {"https://u": "x" * 50}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "q"})
    assert "…" in out
    assert "x" * 10 in out and "x" * 11 not in out


def test_web_search单页正文抓取失败时跳过保留摘要(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(fetch_count=1, content_chars=100))
    fake = _FakeDDGS()
    fake.results = [{"title": "标题A", "href": "https://bad", "body": "摘要A"}]
    fake.extract_error_urls = {"https://bad"}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "q"})
    assert "标题A" in out and "摘要A" in out  # 不崩，正文抓取失败仍保留摘要


def test_web_search只抓取前N个结果的正文(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(fetch_count=1, content_chars=100))
    fake = _FakeDDGS()
    fake.results = [
        {"title": "一", "href": "https://1", "body": "b1"},
        {"title": "二", "href": "https://2", "body": "b2"},
    ]
    fake.contents = {"https://1": "内容1", "https://2": "内容2"}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "q"})
    assert fake.extract_calls == ["https://1"]
    assert "内容1" in out and "内容2" not in out


def test_关闭抓正文开关时不调用extract(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(fetch_content=False))
    fake = _FakeDDGS()
    fake.results = [{"title": "t", "href": "https://u", "body": "b"}]
    fake.contents = {"https://u": "不该出现"}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.web_search.invoke({"query": "q"})
    assert fake.extract_calls == []
    assert "不该出现" not in out


# ---------- Tavily（tavily_search） ----------


def test_tavily返回合成答案与来源(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(tavily_key="tvly-x"))
    payload = {
        "answer": "Python 是一种编程语言。",
        "results": [
            {"title": "维基-Python", "url": "https://wiki/python", "content": "高级语言"},
        ],
    }
    monkeypatch.setattr(ws.httpx, "post", lambda *a, **k: FakeResp(payload))
    out = ws.tavily_search.invoke({"query": "什么是python"})
    assert "Python 是一种编程语言。" in out
    assert "维基-Python" in out and "https://wiki/python" in out


def test_tavily请求带上查询与鉴权(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(tavily_key="tvly-x"))
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return FakeResp({"answer": "", "results": []})

    monkeypatch.setattr(ws.httpx, "post", fake_post)
    ws.tavily_search.invoke({"query": "天气"})
    assert captured["json"]["query"] == "天气"
    # 用 advanced 深度提取，提升赛程/具体日期这类明细查询的准确度
    assert captured["json"]["search_depth"] == "advanced"
    # key 经鉴权头或请求体传递，不应硬编码在 URL
    assert "tvly-x" in str(captured["headers"]) or captured["json"].get("api_key") == "tvly-x"
    assert "tvly-x" not in captured["url"]


def test_tavily调用失败时返回错误文本而不抛出(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(tavily_key="tvly-x"))

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(ws.httpx, "post", boom)
    out = ws.tavily_search.invoke({"query": "x"})
    assert "失败" in out and "network down" in out


# ---------- 工具注册（自动切换的前提：两个工具都绑定给模型由其选择） ----------


def test_关闭总开关时不注册任何搜索工具(monkeypatch):
    # 即使配置了 Tavily key，总开关关闭后两个工具都不注册
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(enabled=False, tavily_key="tvly-x"))
    assert ws.build_web_search_tools() == []


def test_未配置tavily时注册web_search与fetch_url(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(tavily_key=""))
    names = [t.name for t in ws.build_web_search_tools()]
    assert names == ["web_search", "fetch_url"]


def test_fetch_url返回指定网页正文(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(content_chars=1000))
    fake = _FakeDDGS()
    fake.contents = {"https://x": "这是页面正文内容"}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    out = ws.fetch_url.invoke({"url": "https://x"})
    assert "这是页面正文内容" in out
    assert fake.extract_calls == ["https://x"]


def test_fetch_url抓取失败时返回提示(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(content_chars=1000))
    fake = _FakeDDGS()
    fake.extract_error_urls = {"https://bad"}
    monkeypatch.setattr(ws, "DDGS", lambda: fake)
    assert "未能读取" in ws.fetch_url.invoke({"url": "https://bad"})


def test_关闭总开关时fetch_url也不注册(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(enabled=False))
    assert ws.build_web_search_tools() == []


def test_配置tavily后同时注册两个工具(monkeypatch):
    monkeypatch.setattr(ws, "get_settings", lambda: _settings(tavily_key="tvly-x"))
    names = [t.name for t in ws.build_web_search_tools()]
    assert "web_search" in names and "tavily_search" in names


def test_web搜索工具按开关接入本地工具集(monkeypatch):
    # LOCAL_TOOLS 在 import 时按配置组装，故不依赖开发者本地 .env：
    # 强制开关开启后重载 tools 模块，验证 web_search 确实被接入。
    import importlib

    import app.llm.tools as tools_mod

    monkeypatch.setattr(ws, "get_settings", lambda: _settings(enabled=True))
    importlib.reload(tools_mod)
    try:
        assert "web_search" in tools_mod.LOCAL_TOOLS
    finally:
        importlib.reload(tools_mod)  # 还原为按真实配置组装
