"""app/llm/client.py 单测：stream_reply 的流式产出、工具调用闭环与错误处理。

mock 说明：
- ChatOpenAI 用 FakeLLM 替换——不触达真实 LLM 服务，且能精确控制每一轮产出的 chunk。
- get_mcp_tools 置空——隔离 MCP，专注验证 client 自身逻辑。
- settings.llm_api_key 用 monkeypatch 设置——避免依赖真实 .env 配置。
"""
import pytest

import app.llm.client as client
from app.llm.client import LlmCallError, stream_reply
from tests.fakes import FakeChunk, FakeLLM, FakeTool


async def _collect(agen):
    return [item async for item in agen]


@pytest.fixture
def patch_llm(monkeypatch):
    """提供工厂：用给定 FakeLLM 替换 ChatOpenAI，并确保 api_key 已配置、MCP 工具为空。"""
    monkeypatch.setattr(client.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(client, "get_mcp_tools", lambda: [])

    def _apply(fake_llm: FakeLLM) -> FakeLLM:
        monkeypatch.setattr(client, "ChatOpenAI", lambda **kwargs: fake_llm)
        return fake_llm

    return _apply


async def test_未配置api_key时抛出LlmCallError(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_api_key", "")
    with pytest.raises(LlmCallError):
        await _collect(stream_reply([{"role": "user", "content": "hi"}]))


async def test_无工具调用时按序产出思维链与正文增量(patch_llm):
    fake = patch_llm(FakeLLM(rounds=[[FakeChunk(content="你好", reasoning="思考中")]]))
    out = await _collect(stream_reply([{"role": "user", "content": "hi"}]))
    assert out == [("reasoning", "思考中"), ("content", "你好")]
    assert fake.astream_calls == 1  # 无工具调用 → 单轮即结束


async def test_模型请求工具后执行并在下一轮给出最终回复(patch_llm):
    # 第一轮模型只请求调用 get_current_date（无正文）；第二轮给出最终回复
    round1 = [FakeChunk(tool_calls=[{"name": "get_current_date", "args": {}, "id": "call_1"}])]
    round2 = [FakeChunk(content="今天的日期已经查到了")]
    fake = patch_llm(FakeLLM(rounds=[round1, round2]))
    out = await _collect(stream_reply([{"role": "user", "content": "今天几号"}]))
    assert ("content", "今天的日期已经查到了") in out
    assert fake.astream_calls == 2  # 工具调用触发了第二轮


async def test_按请求注入的extra_tools被绑定并可在工具循环中调用(patch_llm):
    # 模型第一轮请求调用注入的知识库检索工具，第二轮给出基于结果的回复
    round1 = [FakeChunk(tool_calls=[{"name": "search_knowledge_base", "args": {"query": "x"}, "id": "c1"}])]
    round2 = [FakeChunk(content="根据知识库给出回答")]
    fake = patch_llm(FakeLLM(rounds=[round1, round2]))
    kb_tool = FakeTool("search_knowledge_base", result="检索到的片段")
    out = await _collect(stream_reply([{"role": "user", "content": "q"}], extra_tools=[kb_tool]))
    assert ("content", "根据知识库给出回答") in out
    assert fake.astream_calls == 2
    assert "search_knowledge_base" in [t.name for t in fake.bound_tools]


async def test_工具调用产出start与end步骤事件(patch_llm):
    # 工具执行前后应各产出一个 ("tool", {...}) 事件，供前端展示执行步骤
    round1 = [FakeChunk(tool_calls=[{"name": "get_current_date", "args": {}, "id": "c1"}])]
    round2 = [FakeChunk(content="ok")]
    patch_llm(FakeLLM(rounds=[round1, round2]))
    out = await _collect(stream_reply([{"role": "user", "content": "今天几号"}]))
    tool_events = [d for k, d in out if k == "tool"]
    assert {"tool": "get_current_date", "phase": "start", "args": {}} in tool_events
    assert {"tool": "get_current_date", "phase": "end"} in tool_events


async def test_工具调用持续到达最大轮数后停止(patch_llm):
    # 每轮模型都请求工具，验证不会无限循环，最多 _MAX_TOOL_ROUNDS 轮
    tool_round = [FakeChunk(tool_calls=[{"name": "get_current_date", "args": {}, "id": "c"}])]
    fake = patch_llm(FakeLLM(rounds=[list(tool_round) for _ in range(client._MAX_TOOL_ROUNDS)]))
    await _collect(stream_reply([{"role": "user", "content": "x"}]))
    assert fake.astream_calls == client._MAX_TOOL_ROUNDS


async def test_启用思考模式时按配置传入reasoning与thinking参数(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(client, "get_mcp_tools", lambda: [])
    monkeypatch.setattr(client.settings, "llm_thinking_enabled", True)
    monkeypatch.setattr(client.settings, "llm_reasoning_effort", "high")
    captured: dict = {}

    def _factory(**kwargs):
        captured.update(kwargs)
        return FakeLLM(rounds=[[FakeChunk(content="ok")]])

    monkeypatch.setattr(client, "ChatOpenAI", _factory)
    await _collect(stream_reply([{"role": "user", "content": "hi"}]))
    assert captured["reasoning_effort"] == "high"
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}


async def test_关闭思考模式时不传reasoning与thinking参数(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(client, "get_mcp_tools", lambda: [])
    monkeypatch.setattr(client.settings, "llm_thinking_enabled", False)
    captured: dict = {}

    def _factory(**kwargs):
        captured.update(kwargs)
        return FakeLLM(rounds=[[FakeChunk(content="ok")]])

    monkeypatch.setattr(client, "ChatOpenAI", _factory)
    await _collect(stream_reply([{"role": "user", "content": "hi"}]))
    assert "reasoning_effort" not in captured
    assert "extra_body" not in captured


async def test_底层调用异常被包装为LlmCallError(patch_llm):
    fake = patch_llm(FakeLLM(raise_on_stream=RuntimeError("network down")))
    with pytest.raises(LlmCallError):
        await _collect(stream_reply([{"role": "user", "content": "x"}]))
