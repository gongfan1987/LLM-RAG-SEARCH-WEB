import type { KbRetrievalScope } from "@/types/knowledgeBase";

export type MessageRole = "user" | "assistant";

/** 一次工具调用（执行步骤），用于展示 AI 的执行过程 */
export interface ChatStep {
  tool: string;
  args?: Record<string, unknown>;
  /** 该步骤是否已执行完成 */
  done: boolean;
}

export interface ChatMessage {
  /** 流式生成过程中用于 React key 与状态匹配的本地 id */
  id: string;
  role: MessageRole;
  content: string;
  /** 思考模式（deepseek-reasoner）下的思维链，仅用于展示，不持久化 */
  reasoning?: string;
  /** 工具调用执行过程（如检索知识库、查询数据库），仅用于展示，不持久化 */
  steps?: ChatStep[];
  created_at?: string;
  /** 是否仍在流式接收中 */
  streaming?: boolean;
}

export interface RemoteMessage {
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface ChatStreamPayload {
  session_id?: number;
  message: string;
  /** 知识库检索范围；省略时后端默认 both（全局+个人，游客退化为仅全局） */
  kb_scope?: KbRetrievalScope;
}

/** 后端 SSE 帧的原始结构：统一用 type 区分事件类型 */
export interface ChatStreamChunk {
  type: "session" | "delta" | "reasoning" | "step" | "done" | "error";
  /** delta / reasoning 事件携带的增量文本 */
  content?: string;
  /** session 事件携带的新会话 id（新建会话场景） */
  session_id?: number;
  /** step 事件：工具名 / 阶段 / 入参 */
  tool?: string;
  phase?: "start" | "end";
  args?: Record<string, unknown>;
  error?: string;
}
