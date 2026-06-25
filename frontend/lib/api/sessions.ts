import { apiFetch } from "@/lib/api/client";
import type {
  ChatSession,
  CreateSessionPayload,
  UpdateSessionPayload,
} from "@/types/session";
import type { RemoteMessage } from "@/types/message";

export function fetchSessions(): Promise<ChatSession[]> {
  return apiFetch<ChatSession[]>("/api/sessions");
}

export function createSession(
  payload: CreateSessionPayload = {}
): Promise<ChatSession> {
  return apiFetch<ChatSession>("/api/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function renameSession(
  id: number,
  payload: UpdateSessionPayload
): Promise<ChatSession> {
  return apiFetch<ChatSession>(`/api/sessions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteSession(id: number): Promise<void> {
  return apiFetch<void>(`/api/sessions/${id}`, {
    method: "DELETE",
  });
}

export function fetchSessionMessages(id: number): Promise<RemoteMessage[]> {
  return apiFetch<RemoteMessage[]>(`/api/sessions/${id}/messages`);
}
