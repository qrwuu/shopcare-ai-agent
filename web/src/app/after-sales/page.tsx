"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getStoredAuth } from "@/lib/api/auth";
import { listMyRefunds, markAfterSalesNotificationsRead, simulateMerchantReceived, simulateRefundComplete, submitReturnTracking } from "@/lib/api/customer";
import { toUserMessage } from "@/lib/api/errors";
import type { RefundRecord } from "@/types/customer";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function AfterSalesPage() {
  const router = useRouter();
  const [records, setRecords] = useState<RefundRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionId, setActionId] = useState<number | null>(null);


  const refresh = async () => {
    setRecords(await listMyRefunds());
  };

  const runAction = async (record: RefundRecord, action: "tracking" | "received" | "complete") => {
    setError("");
    setActionId(record.id);
    try {
      if (action === "tracking") {
        const value = window.prompt("请输入退货物流单号");
        if (!value?.trim()) return;
        await submitReturnTracking(record.id, value.trim());
      }
      if (action === "received") await simulateMerchantReceived(record.id);
      if (action === "complete") await simulateRefundComplete(record.id);
      await refresh();
    } catch (err) {
      setError(toUserMessage(err));
    } finally {
      setActionId(null);
    }
  };

  useEffect(() => {
    const stored = getStoredAuth();
    if (!stored) {
      router.replace("/login?next=/after-sales");
      return;
    }
    if (stored.user.is_admin) {
      router.replace("/admin");
      return;
    }
    void markAfterSalesNotificationsRead().catch(() => undefined);
    const load = () => listMyRefunds()
      .then(setRecords)
      .catch((err) => setError(toUserMessage(err)))
      .finally(() => setLoading(false));
    void load();
    const timer = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(timer);
  }, [router]);

  useEffect(() => {
    const stored = getStoredAuth();
    if (!stored || stored.user.is_admin) return;
    const configured = process.env.NEXT_PUBLIC_WS_BASE_URL || "ws://localhost:18001";
    const websocketBase = configured.endsWith("/") ? configured.slice(0, -1) : configured;
    const socket = new WebSocket(websocketBase + "/api/v1/ws/after-sales?token=" + encodeURIComponent(stored.token));
    socket.onmessage = (event) => { try { if (JSON.parse(event.data).type === "after_sales_updated") void refresh(); } catch {} };
    const heartbeat = window.setInterval(() => { if (socket.readyState === WebSocket.OPEN) socket.send("ping"); }, 25000);
    return () => { window.clearInterval(heartbeat); socket.close(); };
  }, []);

  return (
    <div className="flex flex-1 overflow-y-auto bg-background-base px-6 py-8">
      <main className="mx-auto w-full max-w-4xl">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-mono text-accent">售后记录</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-text-col-primary">申请进度</h1>
          </div>
          <Link href="/chat" className="rounded bg-accent px-4 py-2 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90">继续咨询</Link>
        </div>

        {error && <div className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>}
        {loading ? <p className="text-sm text-text-col-tertiary">正在读取售后记录...</p> : null}

        <div className="grid gap-3">
          {records.map((record) => (
            <section key={record.id} className="rounded border border-border-col bg-background-surface p-4">
              <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
                <div>
                  <h2 className="text-base font-semibold text-text-col-primary">{record.product_name}</h2>
                  <p className="mt-1 text-sm text-text-col-tertiary">订单号 {record.order_sn || "-"} · 申请 #{record.id}</p>
                  <p className="mt-1 text-sm text-text-col-tertiary">{formatTime(record.created_at)}</p>
                </div>
                <div className="text-left md:text-right">
                  <span className="rounded border border-warning/30 bg-warning/5 px-2.5 py-1 text-sm text-warning">{record.status_label}</span>
                  <p className="mt-2 text-sm font-semibold text-accent">¥{record.refund_amount}</p>
                </div>
              </div>
              {record.admin_note && <p className="mt-3 rounded border border-border-col bg-background-base px-3 py-2 text-sm text-text-col-secondary">{record.admin_note}</p>}

              {record.timeline && record.timeline.length > 0 && (
                <div className="mt-3 grid gap-2 border-t border-border-col pt-3">
                  {record.timeline.map((item, index) => (
                    <div key={`${record.id}-${index}`} className="flex gap-2 text-xs">
                      <span className="mt-1 h-2 w-2 rounded-full bg-accent" />
                      <div>
                        <p className="font-medium text-text-col-primary">{item.label}</p>
                        <p className="text-text-col-tertiary">{item.note || formatTime(item.time)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {record.status === "WAITING_RETURN" && <button disabled={actionId === record.id} onClick={() => void runAction(record, "tracking")} className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-subtle disabled:opacity-50">填写退货单号</button>}
                {record.status === "RETURN_SHIPPING" && <button disabled={actionId === record.id} onClick={() => void runAction(record, "received")} className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary hover:border-accent hover:text-accent disabled:opacity-50">模拟商家收货</button>}
                {record.status === "PROCESSING" && <button disabled={actionId === record.id} onClick={() => void runAction(record, "complete")} className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary hover:border-accent hover:text-accent disabled:opacity-50">模拟退款完成</button>}
                {record.return_tracking_number && <span className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-tertiary">退货单号 {record.return_tracking_number}</span>}
              </div>
            </section>
          ))}
          {!loading && records.length === 0 && <p className="rounded border border-border-col bg-background-surface p-6 text-center text-sm text-text-col-tertiary">暂无售后申请记录。</p>}
        </div>
      </main>
    </div>
  );
}
