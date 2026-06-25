"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/types/message";
import { MessageBubble } from "@/components/MessageBubble";

interface MessageListProps {
  messages: ChatMessage[];
}

/** 消息滚动区域，新消息到达时自动滚动到底部 */
export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        发送一条消息，开始对话
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto py-4">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
