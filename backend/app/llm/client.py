"""langchain LLM 客户端：构建 ChatOpenAI、绑定工具、运行流式工具调用循环。

对外只暴露 stream_reply（产出 (kind, text)）与 LlmCallError，屏蔽 langchain 细节；
调用方（chat_service）不感知 ChatOpenAI / 工具循环 / 消息对象等实现。
"""
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.llm.mcp import get_mcp_tools
from app.llm.tools import LOCAL_TOOLS, run_tool, to_lc_messages

settings = get_settings()

# 工具调用的最大轮数：防止模型反复请求工具导致死循环。
_MAX_TOOL_ROUNDS = 5


class LlmCallError(Exception):
    """LLM 调用失败的内部信号，由 stream_reply 抛出，调用方负责转换为 SSE error 事件。"""


def _preview_args(args: object, limit: int = 120) -> dict:
    """把工具入参整理成简短预览（截断过长字符串），用于前端展示执行步骤，避免回灌大字段。"""
    if not isinstance(args, dict):
        return {}
    preview: dict = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > limit:
            preview[key] = value[:limit] + "…"
        else:
            preview[key] = value
    return preview


async def stream_reply(
    messages: list[dict], extra_tools: list | None = None
) -> AsyncGenerator[tuple[str, object], None]:
    """经 langchain（OpenAI 兼容协议）流式调用第三方 LLM，逐段产出增量文本。

    产出 (kind, text) 二元组：kind 为 "reasoning"（思考模式下的思维链增量，
    DeepSeek reasoner 的 reasoning_content 经 langchain 落在 chunk.additional_kwargs）
    或 "content"（最终回复增量）。
    思维链仅用于前端展示，不计入需落库的最终回复，也不回灌进后续上下文。

    工具调用：模型可请求调用本地工具（如 get_current_date）、启动时加载的 MCP 工具
    （如 MySQL MCP server 暴露的数据库查询工具），以及调用方按请求传入的 extra_tools
    （如绑定了用户/范围的知识库检索工具）。当某一轮流式输出包含 tool_calls 时，
    本函数在服务端执行工具、把结果作为 ToolMessage 回灌，再发起下一轮，直到模型给出
    不含工具调用的最终回复（最多 _MAX_TOOL_ROUNDS 轮）。
    工具产生的中间过程不对外产出 content，只有最终回复计入落库。

    失败时抛出 LlmCallError（而非 HTTPException），由上层 stream_chat_reply
    捕获后转换为 SSE error 事件，避免在 StreamingResponse 已经开始响应之后
    再抛出 FastAPI 异常导致连接被异常中断。
    """
    if not settings.llm_api_key:
        raise LlmCallError("服务端未配置 LLM_API_KEY，请联系管理员")

    # 本地工具 + 启动时加载的 MCP 工具 + 按请求注入的工具，合并后绑定；registry 供按名回查。
    tools = [*LOCAL_TOOLS.values(), *get_mcp_tools(), *(extra_tools or [])]
    registry = {t.name: t for t in tools}

    # 思考模式：开启时传 reasoning_effort + extra_body 启用模型推理；关闭则回退普通对话。
    # 两个参数同进同退（都属于 thinking 模式），避免对不支持推理的模型误传导致报错。
    thinking_kwargs: dict = {}
    if settings.llm_thinking_enabled:
        thinking_kwargs["reasoning_effort"] = settings.llm_reasoning_effort
        thinking_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    llm = ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        streaming=True,
        timeout=60.0,
        **thinking_kwargs,
    ).bind_tools(tools)

    lc_messages = to_lc_messages(messages)

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            gathered: AIMessage | None = None
            async for chunk in llm.astream(lc_messages):
                reasoning = chunk.additional_kwargs.get("reasoning_content")
                if reasoning:
                    yield ("reasoning", reasoning)
                if chunk.content:
                    yield ("content", chunk.content)
                gathered = chunk if gathered is None else gathered + chunk

            # 无输出或无工具调用：本轮即最终回复，结束。
            if gathered is None or not gathered.tool_calls:
                return

            # 有工具调用：回灌模型的工具请求 + 工具执行结果，进入下一轮。
            # 同时把每个工具的开始/结束作为 ("tool", {...}) 事件产出，供前端展示执行步骤。
            lc_messages.append(gathered)
            for call in gathered.tool_calls:
                yield ("tool", {"tool": call["name"], "phase": "start", "args": _preview_args(call.get("args"))})
                result = await run_tool(call, registry)
                yield ("tool", {"tool": call["name"], "phase": "end"})
                lc_messages.append(ToolMessage(content=result, tool_call_id=call["id"]))
    except LlmCallError:
        raise
    except Exception as exc:  # langchain/openai 的各类调用异常统一转为内部信号
        raise LlmCallError(f"LLM 服务调用失败: {exc}") from exc
