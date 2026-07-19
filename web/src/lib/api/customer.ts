import type { AttachmentRecord, CustomerOrder, NotificationRecord, RefundRecord } from "@/types/customer";
import { apiFetch } from "./client";

export async function listMyOrders(): Promise<CustomerOrder[]> {
  return apiFetch<CustomerOrder[]>("/api/v1/customer/orders", { auth: true });
}

export async function listMyRefunds(): Promise<RefundRecord[]> {
  return apiFetch<RefundRecord[]>("/api/v1/customer/refunds", { auth: true });
}

export async function restoreDemoData(): Promise<CustomerOrder[]> {
  return apiFetch<CustomerOrder[]>("/api/v1/customer/demo-data/restore", { method: "POST", auth: true });
}


export async function uploadAttachment(input: { file: File; threadId: string; orderSn?: string | null; refundApplicationId?: number | null; attachmentType?: string; }): Promise<AttachmentRecord> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("thread_id", input.threadId);
  form.append("attachment_type", input.attachmentType || "image");
  if (input.orderSn) form.append("order_sn", input.orderSn);
  if (input.refundApplicationId) form.append("refund_application_id", String(input.refundApplicationId));
  return apiFetch<AttachmentRecord>("/api/v1/customer/attachments", { method: "POST", auth: true, body: form });
}

export async function listNotifications(): Promise<NotificationRecord[]> {
  return apiFetch<NotificationRecord[]>("/api/v1/customer/notifications", { auth: true });
}

export async function markNotificationRead(notificationId: number): Promise<NotificationRecord> {
  return apiFetch<NotificationRecord>(`/api/v1/customer/notifications/${notificationId}/read`, { method: "POST", auth: true });
}

export async function markAfterSalesNotificationsRead(): Promise<NotificationRecord[]> {
  return apiFetch<NotificationRecord[]>("/api/v1/customer/notifications/read-after-sales", { method: "POST", auth: true });
}

export async function submitReturnTracking(refundId: number, trackingNumber: string): Promise<RefundRecord> {
  return apiFetch<RefundRecord>(`/api/v1/customer/refunds/${refundId}/return-tracking`, { method: "POST", auth: true, json: { tracking_number: trackingNumber } });
}

export async function simulateMerchantReceived(refundId: number): Promise<RefundRecord> {
  return apiFetch<RefundRecord>(`/api/v1/customer/refunds/${refundId}/simulate-received`, { method: "POST", auth: true });
}

export async function simulateRefundComplete(refundId: number): Promise<RefundRecord> {
  return apiFetch<RefundRecord>(`/api/v1/customer/refunds/${refundId}/simulate-complete`, { method: "POST", auth: true });
}
