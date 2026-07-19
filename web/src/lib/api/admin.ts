import { apiFetch } from "./client";

export interface AuditUser {
  user_id: number;
  nickname: string;
  account: string;
  phone?: string | null;
  email?: string | null;
  registered_at?: string | null;
}

export interface AuditOrderItem {
  name: string;
  qty: number;
  price: number;
  image_url?: string | null;
  attributes: Record<string, string>;
}

export interface AuditOrder {
  order_id: number;
  order_sn: string;
  status: string;
  status_label: string;
  total_amount: number;
  tracking_number?: string | null;
  shipping_address?: string | null;
  created_at?: string | null;
  items: AuditOrderItem[];
}

export interface AuditRefund {
  refund_id: number;
  after_sales_id: number;
  after_sales_status: string;
  after_sales_status_label: string;
  after_sales_type: string;
  status: string;
  status_label: string;
  refund_amount: number;
  reason_detail: string;
  admin_note?: string | null;
  stage?: string | null;
  timeline: Array<{ label: string; note?: string; time: string }>;
}

export interface AuditAttachment {
  id: number;
  attachment_type: string;
  filename: string;
  content_type: string;
  url: string;
  created_at: string;
  is_new_material: boolean;
}

export interface AuditConversationEntry {
  id: number;
  role: string;
  content: string;
  message_type: string;
  created_at: string;
}

export interface AuditHistoryEntry {
  audit_log_id: number;
  action: string;
  action_label: string;
  reason: string;
  comment?: string | null;
  operator_name?: string | null;
  created_at: string;
  reviewed_at?: string | null;
}

export interface AuditOperationEntry {
  time: string;
  title: string;
  detail: string;
  kind: "refund" | "attachment" | "audit" | string;
}

export interface AuditTask {
  audit_log_id: number;
  thread_id: string;
  user_id: number;
  refund_application_id: number | null;
  after_sales_id?: number | null;
  after_sales_status?: string | null;
  after_sales_status_label?: string | null;
  order_id: number | null;
  trigger_reason: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | string;
  action: string;
  action_label: string;
  admin_comment?: string | null;
  context_snapshot: Record<string, unknown>;
  created_at: string;
  reviewed_at?: string | null;
  user?: AuditUser | null;
  order?: AuditOrder | null;
  refund?: AuditRefund | null;
  attachments: AuditAttachment[];
  conversation: AuditConversationEntry[];
  agent_checks: string[];
  policy_checks: string[];
  audit_history: AuditHistoryEntry[];
  operation_log: AuditOperationEntry[];
}

export interface AdminDecisionResponse {
  success: boolean;
  message: string;
  audit_log_id: number;
  action: "APPROVE" | "REJECT" | "REQUEST_INFO" | string;
}

export async function listAuditTasks(input?: { riskLevel?: string; includeHistory?: boolean }): Promise<AuditTask[]> {
  const params = new URLSearchParams();
  if (input?.riskLevel) params.set("risk_level", input.riskLevel);
  if (input?.includeHistory) params.set("include_history", "true");
  const query = params.toString();
  return apiFetch<AuditTask[]>(`/api/v1/admin/tasks${query ? `?${query}` : ""}`, { auth: true });
}

export async function getAuditTask(auditLogId: number): Promise<AuditTask> {
  return apiFetch<AuditTask>(`/api/v1/admin/tasks/${auditLogId}`, { auth: true });
}

export async function submitAuditDecision(
  auditLogId: number,
  action: "APPROVE" | "REJECT" | "REQUEST_INFO",
  adminComment: string
): Promise<AdminDecisionResponse> {
  return apiFetch<AdminDecisionResponse>(`/api/v1/admin/resume/${auditLogId}`, {
    method: "POST",
    auth: true,
    json: { action, admin_comment: adminComment.trim() },
  });
}
