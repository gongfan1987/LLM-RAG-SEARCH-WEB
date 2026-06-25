export interface ChatSession {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface CreateSessionPayload {
  title?: string;
}

export interface UpdateSessionPayload {
  title: string;
}

/** 会话按时间分组展示用的分组键 */
export type SessionGroupKey = "今天" | "昨天" | "7天内" | "更早";
