"use client";

import { useEffect, useState } from "react";
import { ChatSidebar } from "@/components/ChatSidebar";
import { MessageList } from "@/components/MessageList";
import { ChatInput } from "@/components/ChatInput";
import { GuestBanner } from "@/components/GuestBanner";
import { GuestLimitDialog } from "@/components/GuestLimitDialog";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";
import { useChatStore } from "@/store/useChatStore";
import { getGuestTrialRemaining } from "@/lib/utils/anonymousTrial";
import type { KbRetrievalScope } from "@/types/knowledgeBase";

export default function ChatPage() {
  const user = useAuthStore((s) => s.user);
  const activeSessionId = useSessionStore((s) => s.activeSessionId);

  const messagesBySession = useChatStore((s) => s.messagesBySession);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const guestLimitReached = useChatStore((s) => s.guestLimitReached);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopGenerating = useChatStore((s) => s.stopGenerating);
  const loadMessages = useChatStore((s) => s.loadMessages);
  const dismissGuestLimit = useChatStore((s) => s.dismissGuestLimit);

  const [guestRemaining, setGuestRemaining] = useState(getGuestTrialRemaining());

  const draftKey = activeSessionId ?? "__draft__";
  const messages = messagesBySession[draftKey] ?? [];

  useEffect(() => {
    if (activeSessionId && user) {
      loadMessages(activeSessionId);
    }
  }, [activeSessionId, user, loadMessages]);

  async function handleSend(content: string, kbScope: KbRetrievalScope) {
    await sendMessage(activeSessionId, content, kbScope);
    if (!user) {
      setGuestRemaining(getGuestTrialRemaining());
    }
  }

  return (
    <div className="flex flex-1 h-screen">
      <ChatSidebar />

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-14 shrink-0 flex items-center px-5 border-b border-border-subtle">
          <h1 className="text-sm font-medium text-gray-700">AI 对话助手</h1>
        </header>

        {!user && <GuestBanner remaining={guestRemaining} />}

        <MessageList messages={messages} />

        <ChatInput
          disabled={!user && guestRemaining <= 0}
          isStreaming={isStreaming}
          onSend={handleSend}
          onStop={stopGenerating}
          showScope={!!user}
        />
      </main>

      <GuestLimitDialog open={guestLimitReached} onOpenChange={dismissGuestLimit} />
    </div>
  );
}
