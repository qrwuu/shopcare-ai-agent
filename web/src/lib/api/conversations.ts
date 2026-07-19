import { apiFetch } from "./client";
import type { ChatSessionDetail, ChatSessionSummary } from "@/types/conversation";

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  return apiFetch<ChatSessionSummary[]>("/api/v1/customer/chat-sessions", { auth: true });
}

export async function createChatSession(threadId: string): Promise<ChatSessionSummary> {
  return apiFetch<ChatSessionSummary>("/api/v1/customer/chat-sessions", {
    method: "POST",
    auth: true,
    json: { thread_id: threadId },
  });
}

export async function getChatSession(threadId: string): Promise<ChatSessionDetail> {
  return apiFetch<ChatSessionDetail>(`/api/v1/customer/chat-sessions/${encodeURIComponent(threadId)}`, { auth: true });
}

export async function updateChatSession(threadId: string, input: { order_sn?: string | null; title?: string; add_order_card?: boolean }): Promise<ChatSessionSummary> {
  return apiFetch<ChatSessionSummary>(`/api/v1/customer/chat-sessions/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    auth: true,
    json: input,
  });
}

export async function deleteChatSession(threadId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/customer/chat-sessions/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
    auth: true,
  });
}
