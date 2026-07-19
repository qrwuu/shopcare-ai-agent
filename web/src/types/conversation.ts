import type { CustomerOrder } from "./customer";

export interface ChatSessionSummary {
  thread_id: string;
  title: string;
  order_sn?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersistedChatMessage {
  id: number;
  role: "user" | "assistant" | "system" | string;
  content: string;
  message_type: "text" | "order_card" | string;
  order_sn?: string | null;
  card_data?: (Partial<CustomerOrder> & { status_label?: string }) | null;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSessionSummary {
  messages: PersistedChatMessage[];
}
