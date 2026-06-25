import { create } from "zustand";
import type { ChatMessage } from "@/types/message";
import type { KbRetrievalScope } from "@/types/knowledgeBase";
import { fetchSessionMessages } from "@/lib/api/sessions";
import { streamChat } from "@/lib/api/chat";
import {
  hasGuestTrialRemaining,
  incrementGuestTrialCount,
} from "@/lib/utils/anonymousTrial";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";

function createLocalId(): string {
  return `local_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

/** 消息列表按会话分组的 key：登录用户用真实数字 session id，游客/草稿用固定字符串 key */
type MessageGroupKey = number | "__draft__";

interface ChatState {
  messagesBySession: Partial<Record<MessageGroupKey, ChatMessage[]>>;
  isStreaming: boolean;
  /** 游客用尽试用次数时置为 true，用于触发登录引导 */
  guestLimitReached: boolean;
  error: string | null;
  abortController: AbortController | null;

  loadMessages: (sessionId: number) => Promise<void>;
  sendMessage: (
    sessionId: number | null,
    content: string,
    kbScope?: KbRetrievalScope
  ) => Promise<void>;
  stopGenerating: () => void;
  clearError: () => void;
  dismissGuestLimit: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messagesBySession: {},
  isStreaming: false,
  guestLimitReached: false,
  error: null,
  abortController: null,

  loadMessages: async (sessionId) => {
    try {
      const remote = await fetchSessionMessages(sessionId);
      const messages: ChatMessage[] = remote.map((m, idx) => ({
        id: `${sessionId}_${idx}`,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
      }));
      set((state) => ({
        messagesBySession: { ...state.messagesBySession, [sessionId]: messages },
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "加载消息失败" });
    }
  },

  sendMessage: async (sessionId, content, kbScope) => {
    const isLoggedIn = !!useAuthStore.getState().user;

    if (!isLoggedIn && !hasGuestTrialRemaining()) {
      set({ guestLimitReached: true });
      return;
    }

    const draftKey = sessionId ?? "__draft__";
    const userMessage: ChatMessage = {
      id: createLocalId(),
      role: "user",
      content,
    };
    const assistantMessage: ChatMessage = {
      id: createLocalId(),
      role: "assistant",
      content: "",
      streaming: true,
    };

    set((state) => ({
      messagesBySession: {
        ...state.messagesBySession,
        [draftKey]: [
          ...(state.messagesBySession[draftKey] ?? []),
          userMessage,
          assistantMessage,
        ],
      },
      isStreaming: true,
      error: null,
    }));

    const abortController = new AbortController();
    set({ abortController });

    let resolvedSessionId = sessionId;

    const appendDelta = (delta: string) => {
      set((state) => {
        const list = state.messagesBySession[draftKey] ?? [];
        const updated = list.map((m) =>
          m.id === assistantMessage.id ? { ...m, content: m.content + delta } : m
        );
        return { messagesBySession: { ...state.messagesBySession, [draftKey]: updated } };
      });
    };

    const appendReasoning = (delta: string) => {
      set((state) => {
        const list = state.messagesBySession[draftKey] ?? [];
        const updated = list.map((m) =>
          m.id === assistantMessage.id
            ? { ...m, reasoning: (m.reasoning ?? "") + delta }
            : m
        );
        return { messagesBySession: { ...state.messagesBySession, [draftKey]: updated } };
      });
    };

    const updateStep = (
      tool: string,
      phase: "start" | "end",
      args?: Record<string, unknown>
    ) => {
      set((state) => {
        const list = state.messagesBySession[draftKey] ?? [];
        const updated = list.map((m) => {
          if (m.id !== assistantMessage.id) return m;
          const steps = [...(m.steps ?? [])];
          if (phase === "start") {
            steps.push({ tool, args, done: false });
          } else {
            // 把最近一个同名且未完成的步骤标记为完成
            for (let i = steps.length - 1; i >= 0; i--) {
              if (steps[i].tool === tool && !steps[i].done) {
                steps[i] = { ...steps[i], done: true };
                break;
              }
            }
          }
          return { ...m, steps };
        });
        return { messagesBySession: { ...state.messagesBySession, [draftKey]: updated } };
      });
    };

    const finishStreaming = () => {
      set((state) => {
        const list = state.messagesBySession[draftKey] ?? [];
        const updated = list.map((m) =>
          m.id === assistantMessage.id
            ? {
                ...m,
                streaming: false,
                // 流结束后把残留的「执行中」步骤标记完成，避免 spinner 一直转
                steps: m.steps?.map((s) => (s.done ? s : { ...s, done: true })),
              }
            : m
        );

        // 若是新会话（无 sessionId），用后端返回的真实 id 重新挂载消息列表
        const messagesBySession = { ...state.messagesBySession };
        if (!sessionId && resolvedSessionId) {
          delete messagesBySession[draftKey];
          messagesBySession[resolvedSessionId] = updated;
        } else {
          messagesBySession[draftKey] = updated;
        }

        return { messagesBySession, isStreaming: false, abortController: null };
      });

      if (!isLoggedIn) {
        incrementGuestTrialCount();
      }
    };

    await streamChat(
      { session_id: sessionId ?? undefined, message: content, kb_scope: kbScope },
      {
        signal: abortController.signal,
        onDelta: appendDelta,
        onReasoning: appendReasoning,
        onStep: updateStep,
        onSessionId: (id) => {
          resolvedSessionId = id;
          if (!sessionId) {
            useSessionStore.getState().selectSession(id);
          }
        },
        onDone: finishStreaming,
        onError: (message) => {
          set({ error: message, isStreaming: false, abortController: null });
        },
      }
    );
  },

  stopGenerating: () => {
    const { abortController } = get();
    abortController?.abort();
  },

  clearError: () => set({ error: null }),
  dismissGuestLimit: () => set({ guestLimitReached: false }),
}));
