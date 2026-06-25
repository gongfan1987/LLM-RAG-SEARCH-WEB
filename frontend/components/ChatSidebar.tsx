"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";
import { groupSessionsByDate } from "@/lib/utils/groupSessionsByDate";
import { SessionItem } from "@/components/SessionItem";

/** 主对话页侧边栏：登录用户可见历史会话分组列表，游客仅展示登录引导 */
export function ChatSidebar() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const initialized = useAuthStore((s) => s.initialized);
  const sessions = useSessionStore((s) => s.sessions);
  const activeSessionId = useSessionStore((s) => s.activeSessionId);
  const loadSessions = useSessionStore((s) => s.loadSessions);
  const selectSession = useSessionStore((s) => s.selectSession);
  const addSession = useSessionStore((s) => s.addSession);
  const rename = useSessionStore((s) => s.rename);
  const remove = useSessionStore((s) => s.remove);

  useEffect(() => {
    if (initialized && user) {
      loadSessions();
    }
  }, [initialized, user, loadSessions]);

  const grouped = groupSessionsByDate(sessions);

  async function handleNewSession() {
    selectSession(null);
    if (user) {
      await addSession();
    }
  }

  return (
    <aside className="w-64 shrink-0 h-full bg-white border-r border-border-subtle flex flex-col">
      <div className="p-3">
        <button
          type="button"
          onClick={handleNewSession}
          className="w-full flex items-center justify-center gap-2 rounded-xl border border-border-subtle bg-surface px-3 py-2.5 text-sm font-medium text-gray-700 hover:border-brand hover:text-brand transition-colors"
        >
          <PlusIcon />
          新建对话
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 space-y-4">
        {!user && (
          <p className="px-3 py-2 text-xs text-gray-400">
            登录后可保存并查看历史会话
          </p>
        )}

        {user &&
          grouped.map((group) => (
            <div key={group.key}>
              <div className="px-3 pb-1 text-xs font-medium text-gray-400">
                {group.key}
              </div>
              <div className="space-y-0.5">
                {group.sessions.map((session) => (
                  <SessionItem
                    key={session.id}
                    session={session}
                    active={session.id === activeSessionId}
                    onSelect={() => selectSession(session.id)}
                    onRename={(title) => rename(session.id, title)}
                    onDelete={() => remove(session.id)}
                  />
                ))}
              </div>
            </div>
          ))}
      </div>

      <div className="p-3 border-t border-border-subtle space-y-0.5">
        {user ? (
          <>
            <Link
              href="/knowledge-base"
              className="w-full flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-gray-600 hover:bg-surface transition-colors"
            >
              <BookIcon />
              <span>知识库</span>
            </Link>
            <button
              type="button"
              onClick={() => router.push("/settings")}
              className="w-full flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-gray-600 hover:bg-surface transition-colors"
            >
              <UserIcon />
              <span className="truncate">{user.username}</span>
            </button>
          </>
        ) : (
          <Link
            href="/login"
            className="w-full flex items-center justify-center rounded-xl bg-brand text-brand-foreground px-3 py-2 text-sm font-medium hover:bg-brand/90 transition-colors"
          >
            登录 / 注册
          </Link>
        )}
      </div>
    </aside>
  );
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 5v14M5 12h14" strokeLinecap="round" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5Z" strokeLinejoin="round" />
      <path d="M4 19a2 2 0 0 1 2-2h13" strokeLinecap="round" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 4-6 8-6s8 2 8 6" strokeLinecap="round" />
    </svg>
  );
}
