import { create } from "zustand";
import type { ChatSession } from "@/types/session";
import {
  createSession,
  deleteSession,
  fetchSessions,
  renameSession,
} from "@/lib/api/sessions";

interface SessionState {
  sessions: ChatSession[];
  activeSessionId: number | null;
  loading: boolean;
  error: string | null;

  loadSessions: () => Promise<void>;
  selectSession: (id: number | null) => void;
  addSession: () => Promise<ChatSession | null>;
  rename: (id: number, title: string) => Promise<void>;
  remove: (id: number) => Promise<void>;
  /** 流式结束后，更新对应会话的标题/更新时间用于排序，或插入新会话 */
  upsertSession: (session: ChatSession) => void;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  loading: false,
  error: null,

  loadSessions: async () => {
    set({ loading: true, error: null });
    try {
      const sessions = await fetchSessions();
      set({ sessions, loading: false });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : "加载会话列表失败",
      });
    }
  },

  selectSession: (id) => set({ activeSessionId: id }),

  addSession: async () => {
    try {
      const session = await createSession();
      set((state) => ({
        sessions: [session, ...state.sessions],
        activeSessionId: session.id,
      }));
      return session;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "新建会话失败" });
      return null;
    }
  },

  rename: async (id, title) => {
    try {
      const updated = await renameSession(id, { title });
      set((state) => ({
        sessions: state.sessions.map((s) => (s.id === id ? updated : s)),
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "重命名失败" });
    }
  },

  remove: async (id) => {
    try {
      await deleteSession(id);
      const { activeSessionId, sessions } = get();
      set({
        sessions: sessions.filter((s) => s.id !== id),
        activeSessionId: activeSessionId === id ? null : activeSessionId,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "删除会话失败" });
    }
  },

  upsertSession: (session) =>
    set((state) => {
      const exists = state.sessions.some((s) => s.id === session.id);
      const sessions = exists
        ? state.sessions.map((s) => (s.id === session.id ? session : s))
        : [session, ...state.sessions];
      return { sessions };
    }),
}));
