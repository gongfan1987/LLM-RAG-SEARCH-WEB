"use client";

import { useState, type KeyboardEvent } from "react";
import type { ChatSession } from "@/types/session";
import { ConfirmDialog } from "@/components/ConfirmDialog";

interface SessionItemProps {
  session: ChatSession;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}

/** 侧边栏单个会话项：支持点击选中、行内编辑重命名、删除二次确认 */
export function SessionItem({ session, active, onSelect, onRename, onDelete }: SessionItemProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(session.title);
  const [confirmOpen, setConfirmOpen] = useState(false);

  function commitRename() {
    const trimmed = title.trim();
    setEditing(false);
    if (trimmed && trimmed !== session.title) {
      onRename(trimmed);
    } else {
      setTitle(session.title);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") commitRename();
    if (e.key === "Escape") {
      setTitle(session.title);
      setEditing(false);
    }
  }

  return (
    <div
      className={`group flex items-center gap-1 rounded-xl px-3 py-2 cursor-pointer text-sm transition-colors ${
        active ? "bg-brand/10 text-brand" : "hover:bg-surface text-gray-700"
      }`}
      onClick={() => !editing && onSelect()}
    >
      {editing ? (
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={commitRename}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 bg-white rounded-md px-1.5 py-0.5 outline-none border border-brand text-sm"
        />
      ) : (
        <span className="flex-1 truncate">{session.title || "新对话"}</span>
      )}

      {!editing && (
        <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
          <button
            type="button"
            aria-label="重命名"
            onClick={(e) => {
              e.stopPropagation();
              setEditing(true);
            }}
            className="p-1 rounded-md hover:bg-gray-200 text-gray-500"
          >
            <PencilIcon />
          </button>
          <button
            type="button"
            aria-label="删除"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmOpen(true);
            }}
            className="p-1 rounded-md hover:bg-gray-200 text-gray-500"
          >
            <TrashIcon />
          </button>
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="删除该会话？"
        description="删除后将无法恢复该会话的全部消息记录。"
        onConfirm={onDelete}
      />
    </div>
  );
}

function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 20h9" strokeLinecap="round" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 6h18" strokeLinecap="round" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
