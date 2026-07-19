import type { ChatStreamEvent } from "./events";

export interface ChatRequestInput {
  message: string;
  sessionId?: string | null;
  threadId?: string | null;
  customerId: string;
  orderSn?: string | null;
  signal?: AbortSignal;
  onEvent?: (event: ChatStreamEvent) => void;
}

export interface ChatSendResult {
  session_id: string;
  thread_id: string;
  order_sn?: string | null;
  content: string;
}

export interface BackendChatRequest {
  question: string;
  thread_id: string;
  order_sn?: string | null;
}
