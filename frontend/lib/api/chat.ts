import { API_BASE_URL, ApiError, buildStreamHeaders } from "@/lib/api/client";
import type { ChatStreamChunk, ChatStreamPayload } from "@/types/message";

export interface StreamChatOptions {
  onDelta: (delta: string) => void;
  /** 思考模式下的思维链增量（deepseek-reasoner），可选 */
  onReasoning?: (delta: string) => void;
  /** 工具调用执行步骤（开始/结束），用于展示执行过程 */
  onStep?: (tool: string, phase: "start" | "end", args?: Record<string, unknown>) => void;
  onSessionId?: (sessionId: number) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
  signal?: AbortSignal;
}

/**
 * 解析 SSE 文本块。后端按 "data: {...}\n\n" 格式发送 JSON 分片，
 * 这里手动按事件分隔符切分，兼容一次读取到多条事件或半条事件的情况。
 */
function parseSseBuffer(
  buffer: string
): { events: ChatStreamChunk[]; rest: string } {
  const events: ChatStreamChunk[] = [];
  const parts = buffer.split("\n\n");
  // 最后一段可能是不完整的事件，留给下一次读取继续拼接
  const rest = parts.pop() ?? "";

  for (const part of parts) {
    const line = part
      .split("\n")
      .find((l) => l.startsWith("data:"));
    if (!line) continue;
    const jsonText = line.slice("data:".length).trim();
    if (!jsonText) continue;
    try {
      events.push(JSON.parse(jsonText) as ChatStreamChunk);
    } catch {
      // 忽略无法解析的分片，避免单条脏数据中断整个流
    }
  }

  return { events, rest };
}

/**
 * 发起对话流式请求。未登录用户的匿名标识由 apiFetch 同款 header 构造逻辑
 * 自动附带（X-Anonymous-Id），已登录用户自动带 Authorization。
 */
export async function streamChat(
  payload: ChatStreamPayload,
  options: StreamChatOptions
): Promise<void> {
  const { onDelta, onReasoning, onStep, onSessionId, onDone, onError, signal } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      headers: buildStreamHeaders(),
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) return;
    onError?.(err instanceof Error ? err.message : "网络请求失败");
    return;
  }

  if (!response.ok || !response.body) {
    const message =
      response.status === 401
        ? "登录状态已失效，请重新登录"
        : `请求失败 (${response.status})`;
    onError?.(message);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSseBuffer(buffer);
      buffer = rest;

      for (const event of events) {
        if (event.type === "error") {
          onError?.(event.error ?? "对话流发生未知错误");
          return;
        }
        if (event.type === "delta" && event.content) {
          onDelta(event.content);
        }
        if (event.type === "reasoning" && event.content) {
          onReasoning?.(event.content);
        }
        if (event.type === "step" && event.tool && event.phase) {
          onStep?.(event.tool, event.phase, event.args);
        }
        if (event.type === "session" && event.session_id != null) {
          onSessionId?.(event.session_id);
        }
        if (event.type === "done") {
          onDone?.();
          return;
        }
      }
    }
    onDone?.();
  } catch (err) {
    if (signal?.aborted) {
      // 用户主动点击"停止生成"，按正常结束处理
      onDone?.();
      return;
    }
    const message =
      err instanceof ApiError ? err.message : "对话流读取中断";
    onError?.(message);
  }
}
