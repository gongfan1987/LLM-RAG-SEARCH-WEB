"use client";

import { useState } from "react";

interface CopyButtonProps {
  text: string;
  className?: string;
}

/** 通用复制按钮，用于代码块和消息内容的快速复制 */
export function CopyButton({ text, className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 剪贴板权限不可用时静默失败
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`text-xs px-2 py-1 rounded-md border border-border-subtle bg-white/80 text-gray-500 hover:text-brand hover:border-brand transition-colors ${className ?? ""}`}
    >
      {copied ? "已复制" : "复制"}
    </button>
  );
}
