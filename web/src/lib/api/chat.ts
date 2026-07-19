import type { BackendChatRequest, ChatRequestInput, ChatSendResult } from "@/types/chat";
import { apiStream } from "./client";
import { FrontendApiError, modelServiceError, streamInterruptedError } from "./errors";
import { loadSession, saveSession } from "./storage";

function createId(prefix: string): string {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${id}`;
}

function ensureSession(customerId: string, sessionId?: string | null, threadId?: string | null) {
  const stored = loadSession(customerId);
  const session = {
    session_id: sessionId || stored?.session_id || createId("session"),
    thread_id: threadId || stored?.thread_id || createId("thread"),
    customer_id: customerId,
    updated_at: new Date().toISOString(),
  };
  saveSession(session);
  return session;
}

function parseSseBlock(block: string): string[] {
  return block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());
}

export async function sendChatMessage(input: ChatRequestInput): Promise<ChatSendResult> {
  const session = ensureSession(input.customerId, input.sessionId, input.threadId);
  const body: BackendChatRequest = { question: input.message, thread_id: session.thread_id, order_sn: input.orderSn || undefined };

  input.onEvent?.({ type: "process", step: "request", label: "Sending message", status: "running" });

  const response = await apiStream("/api/v1/chat", {
    method: "POST",
    auth: true,
    json: body,
    signal: input.signal,
  });

  const contentType = response.headers.get("content-type") || "";
  if (!response.body && contentType.includes("application/json")) {
    const data = await response.json();
    const content = typeof data?.answer === "string" ? data.answer : "";
    input.onEvent?.({ type: "final", content });
    return { ...session, content };
  }

  if (!response.body) throw streamInterruptedError();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let fullContent = "";
  let completed = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";

      for (const block of blocks) {
        for (const dataLine of parseSseBlock(block)) {
          if (!dataLine) continue;
          if (dataLine === "[DONE]") {
            completed = true;
            input.onEvent?.({ type: "process", step: "response", label: "Response complete", status: "completed" });
            input.onEvent?.({ type: "final", content: fullContent });
            saveSession({ ...session, updated_at: new Date().toISOString() });
            return { ...session, content: fullContent };
          }

          let event: unknown;
          try {
            event = JSON.parse(dataLine);
          } catch {
            continue;
          }

          if (event && typeof event === "object" && "token" in event) {
            const token = String((event as { token: unknown }).token || "");
            if (token) {
              fullContent += token;
              input.onEvent?.({ type: "message", content: token });
            }
          } else if (event && typeof event === "object" && "error" in event) {
            input.onEvent?.({ type: "process", step: "response", label: "Backend error", status: "failed" });
            throw modelServiceError();
          }
        }
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw streamInterruptedError();
    }
    if (error instanceof FrontendApiError) throw error;
    throw streamInterruptedError();
  }

  if (!completed) {
    throw streamInterruptedError();
  }

  return { ...session, content: fullContent };
}
