"""对话核心业务逻辑：组织上下文、流式落库，LLM 调用委托给 app.llm 组件。

职责边界：
- 游客模式 / 登录模式的分支判断、额度校验在这里完成（调用 guest_quota_service）。
- 会话归属校验复用 session_service。
- 上下文拼接、SSE 事件封装、落库等业务规则在本文件。
- 与第三方 LLM 的交互（ChatOpenAI、工具调用循环、消息转换）已抽离到 app.llm 组件，
  本文件仅通过 stream_reply / LlmCallError 这一对外接口调用，不感知 langchain 细节。
"""
import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.llm import LlmCallError, stream_reply
from app.models.chat_session import ChatSession
from app.models.user import User
from app.schemas.chat import ChatStreamRequest
from app.schemas.session import SessionCreateRequest
from app.services import (
    conversation_index_service,
    guest_quota_service,
    message_service,
    rag_service,
    resource_service,
    session_service,
)

SYSTEM_PROMPT = "你是一个有帮助的AI助手。"
# 当本轮挂载了知识库检索工具时，追加到系统提示，提示模型主动使用该工具。
KB_TOOL_HINT = (
    "当用户的问题可能与其上传到知识库的文档/资料有关时，"
    "请先调用 search_knowledge_base 工具检索，再基于检索结果回答。"
)

# 持有后台任务的强引用，避免 fire-and-forget 任务被 GC 提前回收（asyncio 已知坑）。
_background_tasks: set = set()


def _run_in_background(coro) -> None:
    """以「发后不管」方式跑一个协程：不阻塞当前流程，完成后自动清理引用。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error_event(message: str) -> str:
    """构造与前端约定一致的错误事件帧：{"type": "error", "error": "..."}。

    StreamingResponse 在 generator 产出第一段数据前就已经发出 200 状态行，
    此时再 raise 异常会导致连接异常中断而不是一个正常的 HTTP 错误响应，
    因此所有面向调用方的错误都必须以 SSE 事件的形式 yield 出去，而不是 raise。
    """
    return _sse_event({"type": "error", "error": message})


def _resolve_session_for_user(db: Session, user: User, session_id: int | None) -> ChatSession:
    if session_id is not None:
        return session_service.get_owned_session(db, user, session_id)
    return session_service.create_session(db, user, payload=SessionCreateRequest(title=None))


def _build_context_messages(
    db: Session,
    session: ChatSession | None,
    latest_user_message: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    if session is not None:
        history = message_service.list_messages(db, session)
        messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append({"role": "user", "content": latest_user_message})
    return messages


async def stream_chat_reply(
    db: Session,
    payload: ChatStreamRequest,
    user: User | None,
    guest_identity: str | None,
) -> AsyncGenerator[str, None]:
    """统一入口：区分游客模式 / 登录模式，产出 SSE data 行。

    设计约定：generator 内部一旦开始 yield，HTTP 响应已经以 200 状态码发出，
    因此所有错误场景（游客超额、会话不存在、LLM 调用失败等）都通过 yield 一个
    {"type": "error", "error": "..."} 事件帧来通知前端，然后 return 正常结束流，
    不再 raise HTTPException，避免连接被异常中断。
    """

    session: ChatSession | None = None

    if user is not None:
        # 登录模式：不限次数，落库保存历史
        try:
            session = _resolve_session_for_user(db, user, payload.session_id)
        except HTTPException as exc:
            yield _sse_error_event(str(exc.detail))
            return
        user_message = message_service.append_message(db, session.id, role="user", content=payload.message)
        yield _sse_event({"type": "session", "session_id": session.id})
    else:
        # 游客模式：基于 anonymous_id/IP 限额，不落库（游客无持久会话）
        if guest_identity is None:
            yield _sse_error_event("无法识别游客身份")
            return
        try:
            guest_quota_service.check_and_increment_quota(db, guest_identity)
        except HTTPException as exc:
            yield _sse_error_event(str(exc.detail))
            return

    # RAG 以「工具」形式接入：按请求范围构造知识库检索工具，交由模型在需要时自行调用，
    # 而非每轮强制召回拼接。构造只是组装工具对象（无 IO）；真正的向量检索在模型调用工具时
    # 经工具循环执行（其内部阻塞 IO 由 langchain 工具的 ainvoke 放线程池）。
    user_id = user.id if user is not None else None
    kb_tool = rag_service.make_kb_search_tool(user_id, payload.kb_scope)
    extra_tools = [kb_tool] if kb_tool is not None else []
    system_prompt = SYSTEM_PROMPT + (KB_TOOL_HINT if kb_tool is not None else "")
    context_messages = _build_context_messages(db, session, payload.message, system_prompt)

    full_reply_parts: list[str] = []
    try:
        async for kind, data in stream_reply(context_messages, extra_tools=extra_tools):
            if kind == "reasoning":
                # 思维链仅透传给前端展示，不计入落库的最终回复
                yield _sse_event({"type": "reasoning", "content": data})
                continue
            if kind == "tool":
                # 工具调用的开始/结束，作为「执行步骤」透传给前端展示，不计入落库回复
                yield _sse_event({"type": "step", **data})
                continue
            full_reply_parts.append(data)
            yield _sse_event({"type": "delta", "content": data})
    except LlmCallError as exc:
        yield _sse_error_event(str(exc))
        return

    full_reply = "".join(full_reply_parts)
    if user is not None and session is not None:
        # 落库前把回复中内联的 base64 资源转存 OSS、替换为外链，避免历史消息膨胀。
        # oss2 为阻塞 IO，放到线程池执行，避免阻塞流式 generator 所在的事件循环。
        stored_reply = await asyncio.to_thread(resource_service.store_inline_resources, full_reply)
        assistant_message = message_service.append_message(
            db, session.id, role="assistant", content=stored_reply
        )
        # 把本轮「用户提问 + AI 回复」自动索引进 Milvus，供后续检索（RAG）。
        # 索引是旁路收益、不影响本次回复，故「发后不管」放后台跑，避免阻塞 done 事件、
        # 拖慢生成结束的体感（embedding/milvus 为阻塞 IO，放线程池；内部已自动降级）。
        _run_in_background(
            asyncio.to_thread(
                conversation_index_service.index_messages,
                [
                    {"id": user_message.id, "session_id": session.id, "role": "user", "text": payload.message},
                    {"id": assistant_message.id, "session_id": session.id, "role": "assistant", "text": stored_reply},
                ],
            )
        )

    yield _sse_event({"type": "done"})
