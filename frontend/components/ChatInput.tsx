"use client";

import { useState, type KeyboardEvent } from "react";
import type { KbRetrievalScope } from "@/types/knowledgeBase";

interface ChatInputProps {
  disabled: boolean;
  isStreaming: boolean;
  onSend: (content: string, kbScope: KbRetrievalScope) => void;
  onStop: () => void;
  /** 是否展示知识库检索范围选择（仅登录用户有知识库） */
  showScope?: boolean;
}

const SCOPE_OPTIONS: { value: KbRetrievalScope; label: string }[] = [
  { value: "both", label: "全局 + 个人" },
  { value: "global", label: "仅全局" },
  { value: "personal", label: "仅个人" },
  { value: "none", label: "关闭" },
];

/** 底部输入区：回车发送，Shift+Enter 换行，生成中显示"停止生成" */
export function ChatInput({
  disabled,
  isStreaming,
  onSend,
  onStop,
  showScope = false,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [kbScope, setKbScope] = useState<KbRetrievalScope>("both");

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed, kbScope);
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="border-t border-border-subtle bg-white px-4 py-3">
      {showScope && (
        <div className="max-w-3xl mx-auto mb-2 flex items-center justify-end gap-1.5 text-xs text-gray-400">
          <span>知识库检索</span>
          <select
            value={kbScope}
            onChange={(e) => setKbScope(e.target.value as KbRetrievalScope)}
            className="rounded-lg border border-border-subtle bg-white px-2 py-1 text-xs text-gray-600 outline-none focus:border-brand transition-colors"
          >
            {SCOPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="max-w-3xl mx-auto flex items-end gap-2 rounded-2xl border border-border-subtle bg-surface px-3 py-2 shadow-sm focus-within:border-brand">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          rows={1}
          disabled={disabled}
          className="flex-1 resize-none bg-transparent outline-none text-[15px] py-1.5 max-h-40 disabled:opacity-50"
        />
        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            className="shrink-0 rounded-xl bg-gray-900 text-white text-sm px-4 py-2 hover:bg-gray-700 transition-colors"
          >
            停止生成
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            className="shrink-0 rounded-xl bg-brand text-brand-foreground text-sm px-4 py-2 hover:bg-brand/90 transition-colors disabled:opacity-40 disabled:hover:bg-brand"
          >
            发送
          </button>
        )}
      </div>
    </div>
  );
}
