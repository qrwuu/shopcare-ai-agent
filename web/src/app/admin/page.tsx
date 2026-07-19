"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, FileText, Image as ImageIcon, LoaderCircle, MessageCircleMore, Package, Paperclip, RefreshCw, ShieldCheck, UserRound, XCircle } from "lucide-react";
import { getStoredAuth, logout } from "@/lib/api/auth";
import { toUserMessage } from "@/lib/api/errors";
import { type AuditAttachment, type AuditTask, listAuditTasks, submitAuditDecision } from "@/lib/api/admin";
import type { StoredAuthState } from "@/types/auth";

const risks: Record<string, string> = {
  LOW: "border-success/30 bg-success/10 text-success",
  MEDIUM: "border-warning/30 bg-warning/10 text-warning",
  HIGH: "border-danger/30 bg-danger/10 text-danger",
  CRITICAL: "border-danger/40 bg-danger/10 text-danger",
};

function time(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function waiting(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 60) return "已等待 " + Math.max(1, minutes) + " 分钟";
  if (minutes < 1440) return "已等待 " + Math.floor(minutes / 60) + " 小时";
  return "已等待 " + Math.floor(minutes / 1440) + " 天";
}

function asset(item: AuditAttachment) {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "") + item.url;
}

function Risk({ value }: { value: string }) {
  return <span className={"rounded-full border px-2.5 py-1 text-xs font-semibold " + (risks[value] || risks.LOW)}>{value} 风险</span>;
}

function Title({ icon, title, hint }: { icon: React.ReactNode; title: string; hint?: string }) {
  return <div className="mb-4 flex gap-2"><span className="mt-0.5 text-accent">{icon}</span><div><h2 className="text-base font-semibold text-text-col-primary">{title}</h2>{hint && <p className="mt-0.5 text-xs leading-5 text-text-col-tertiary">{hint}</p>}</div></div>;
}

function Item({ task, active, onClick }: { task: AuditTask; active: boolean; onClick: () => void }) {
  const product = task.order?.items?.map((item) => item.name).join("、") || "待核实订单";
  return <button onClick={onClick} className={"w-full border-b border-border-col px-4 py-4 text-left hover:bg-accent/10 " + (active ? "border-l-4 border-l-accent bg-accent/10 pl-3" : "")}>
    <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="truncate text-sm font-semibold text-text-col-primary">{task.user?.nickname || "用户 #" + task.user_id}</p><p className="mt-0.5 truncate text-xs text-text-col-tertiary">{task.user?.account || "账号 #" + task.user_id} · {product}</p></div><Risk value={task.risk_level} /></div>
    <p className="mt-2 line-clamp-2 text-sm leading-5 text-text-col-secondary">{task.trigger_reason}</p>
    <div className="mt-3 flex justify-between text-xs text-text-col-tertiary"><span>{task.refund?.status_label || task.action_label}</span><span>{time(task.created_at)}</span></div>
  </button>;
}

function Attachments({ items }: { items: AuditAttachment[] }) {
  if (!items.length) return <p className="rounded-xl border border-dashed border-border-col px-4 py-7 text-center text-sm text-text-col-tertiary">用户暂未上传图片或售后凭证</p>;
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">{items.map((item) => <a key={item.id} href={asset(item)} target="_blank" rel="noreferrer" className="group overflow-hidden rounded-xl border border-border-col bg-background-raised hover:border-accent/30"><div className="relative aspect-[4/3] overflow-hidden bg-background-base"><img src={asset(item)} alt={item.filename} className="h-full w-full object-cover transition-transform group-hover:scale-105" />{item.is_new_material && <span className="absolute left-2 top-2 rounded-full bg-accent px-2 py-1 text-[11px] font-semibold text-accent-subtle">本次补充</span>}</div><div className="px-2.5 py-2"><p className="truncate text-xs font-medium text-text-col-secondary">{item.filename}</p><p className="mt-0.5 text-[11px] text-text-col-tertiary">{time(item.created_at)}</p></div></a>)}</div>;
}

export default function AdminPage() {
  const [auth, setAuth] = useState<StoredAuthState | null>(null);
  const [queue, setQueue] = useState<AuditTask[]>([]);
  const [history, setHistory] = useState<AuditTask[]>([]);
  const [tab, setTab] = useState<"queue" | "history">("queue");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState("");

  const shown = tab === "queue" ? queue : history;
  const selected = useMemo(() => [...queue, ...history].find((item) => item.audit_log_id === selectedId) || shown[0] || null, [queue, history, shown, selectedId]);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setError("");
      const result = await Promise.all([listAuditTasks(), listAuditTasks({ includeHistory: true })]);
      setQueue(result[0]);
      setHistory(result[1]);
      setSelectedId((id) => {
        const all = result[0].concat(result[1]);
        if (id && all.some((item) => item.audit_log_id === id)) return id;
        return (tab === "queue" ? result[0][0] : result[1][0])?.audit_log_id || all[0]?.audit_log_id || null;
      });
    } catch (err) {
      setError(toUserMessage(err));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    const stored = getStoredAuth();
    if (!stored || !stored.user.is_admin) {
      window.location.replace("/admin/login");
      return;
    }
    setAuth(stored);
    void load();
  }, [load]);

  useEffect(() => {
    if (!auth) return;
    const timer = window.setInterval(() => void load(true), 12000);
    return () => window.clearInterval(timer);
  }, [auth, load]);

  useEffect(() => {
    if (!auth) return;
    const configured = process.env.NEXT_PUBLIC_WS_BASE_URL || "ws://localhost:18001";
    const websocketBase = configured.endsWith("/") ? configured.slice(0, -1) : configured;
    const socket = new WebSocket(websocketBase + "/api/v1/ws/admin/" + auth.user.user_id + "?token=" + encodeURIComponent(auth.token));
    socket.onmessage = () => void load(true);
    const heartbeat = window.setInterval(() => { if (socket.readyState === WebSocket.OPEN) socket.send("ping"); }, 25000);
    return () => { window.clearInterval(heartbeat); socket.close(); };
  }, [auth, load]);

  useEffect(() => setNote(selected?.action === "PENDING" ? "" : selected?.admin_comment || ""), [selected?.audit_log_id, selected?.action, selected?.admin_comment]);

  const chooseTab = (value: "queue" | "history") => {
    setTab(value);
    setSelectedId((value === "queue" ? queue[0] : history[0])?.audit_log_id || null);
  };

  const decide = async (action: "APPROVE" | "REJECT" | "REQUEST_INFO") => {
    if (!selected) return;
    if (!note.trim()) {
      setError("请先填写审核说明。该说明会同步给用户和售后记录。");
      return;
    }
    setSubmitting(action);
    try {
      setError("");
      await submitAuditDecision(selected.audit_log_id, action, note);
      await load();
    } catch (err) {
      setError(toUserMessage(err));
    } finally {
      setSubmitting(null);
    }
  };

  if (!auth) return null;
  if (!selected && !loading) return <div className="flex flex-1 items-center justify-center bg-background-base text-text-col-tertiary">暂无审核任务</div>;

  return <div className="flex min-h-0 flex-1 overflow-hidden bg-background-base text-text-col-secondary">
    <aside className="flex w-[340px] shrink-0 flex-col border-r border-border-col bg-background-surface">
      <div className="border-b border-border-col px-5 py-5"><p className="text-xs font-semibold tracking-[0.16em] text-accent">SHOPCARE · INTERNAL</p><h1 className="mt-1 text-xl font-bold text-text-col-primary">售后审核中心</h1><p className="mt-3 text-xs text-text-col-tertiary">审核员：{auth.user.full_name || auth.user.username}</p></div>
      <div className="grid grid-cols-2 gap-2 border-b border-border-col p-3"><button onClick={() => chooseTab("queue")} className={"rounded-xl px-3 py-2 text-left " + (tab === "queue" ? "bg-accent text-accent-subtle" : "bg-background-raised text-text-col-secondary")}><p className="text-xs opacity-80">待我处理</p><p className="mt-0.5 text-lg font-semibold">{queue.length}</p></button><button onClick={() => chooseTab("history")} className={"rounded-xl px-3 py-2 text-left " + (tab === "history" ? "bg-accent text-accent-subtle" : "bg-background-raised text-text-col-secondary")}><p className="text-xs opacity-80">处理记录</p><p className="mt-0.5 text-lg font-semibold">{history.length}</p></button></div>
      <div className="flex items-center justify-between border-b border-border-col px-5 py-3"><p className="text-sm font-semibold text-text-col-secondary">{tab === "queue" ? "等待审核" : "历史审核"}</p><button onClick={() => void load()} className="flex items-center gap-1 text-xs text-accent"><RefreshCw size={13} />刷新</button></div>
      <div className="min-h-0 flex-1 overflow-y-auto">{loading && <div className="p-8 text-center text-sm text-text-col-tertiary"><LoaderCircle className="mx-auto mb-2 animate-spin" size={20} />正在读取审核队列</div>}{!loading && shown.map((task) => <Item key={task.audit_log_id} task={task} active={task.audit_log_id === selected?.audit_log_id} onClick={() => setSelectedId(task.audit_log_id)} />)}{!loading && !shown.length && <p className="p-8 text-center text-sm text-text-col-tertiary">暂无记录</p>}</div>
      <div className="border-t border-border-col p-4"><button onClick={() => { logout(); window.location.assign("/"); }} className="w-full rounded-lg border border-border-col px-3 py-2 text-sm text-text-col-secondary hover:bg-danger/10 hover:text-danger">退出工作台</button></div>
    </aside>

    <main className="min-w-0 flex-1 overflow-y-auto">{selected && <div className="mx-auto max-w-7xl px-6 py-7 lg:px-9">
      {error && <div className="mb-5 flex gap-2 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"><AlertCircle size={17} />{error}</div>}
      <section className="rounded-2xl border border-border-col bg-background-surface p-6 shadow-sm"><div className="flex flex-col justify-between gap-5 lg:flex-row"><div><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-accent">审核单 #{selected.audit_log_id}</span><Risk value={selected.risk_level} /><span className="rounded-full bg-warning/10 px-2.5 py-1 text-xs font-semibold text-warning">{selected.action_label}</span></div><h2 className="mt-3 text-2xl font-bold text-text-col-primary">{selected.trigger_reason}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-text-col-secondary">用户 {selected.user?.nickname || "未知用户"} 的 {selected.refund?.after_sales_type || "售后"}申请已进入人工核验，请结合材料、对话和核验结果完成判断。</p></div><div className="rounded-xl bg-background-raised px-4 py-3 text-sm text-text-col-secondary"><p className="flex gap-2"><Clock3 size={15} className="text-accent" />{selected.action === "PENDING" ? waiting(selected.created_at) : "处理于 " + time(selected.reviewed_at)}</p><p className="mt-2 text-xs text-text-col-tertiary">创建于 {time(selected.created_at)}</p></div></div></section>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]"><div className="space-y-5">
        <section className="rounded-2xl border border-border-col bg-background-surface p-5 shadow-sm"><Title icon={<UserRound size={18} />} title="用户与订单" hint="用昵称、账号和订单商品直接核对归属。" /><div className="grid gap-4 md:grid-cols-2"><div className="rounded-xl bg-background-raised p-4"><div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent/10 font-bold text-accent">{(selected.user?.nickname || "用").slice(0, 1)}</span><div><p className="font-semibold text-text-col-primary">{selected.user?.nickname || "未知用户"}</p><p className="text-xs text-text-col-tertiary">账号 {selected.user?.account || selected.user_id}</p></div></div><p className="mt-4 text-sm text-text-col-secondary">电话：{selected.user?.phone || "未填写"}</p></div><div className="grid grid-cols-2 gap-3 rounded-xl bg-background-raised p-4 text-sm"><div><p className="text-xs text-text-col-tertiary">订单号</p><p className="mt-1 font-semibold text-text-col-primary">{selected.order?.order_sn || "—"}</p></div><div><p className="text-xs text-text-col-tertiary">订单状态</p><p className="mt-1 font-semibold text-text-col-primary">{selected.order?.status_label || "—"}</p></div><div><p className="text-xs text-text-col-tertiary">实付金额</p><p className="mt-1 font-semibold text-text-col-primary">¥{selected.order?.total_amount?.toFixed(2) || "0.00"}</p></div><div><p className="text-xs text-text-col-tertiary">物流单号</p><p className="mt-1 truncate font-semibold text-text-col-primary">{selected.order?.tracking_number || "暂未生成"}</p></div></div></div><div className="mt-4 space-y-3">{selected.order?.items.map((item, index) => <div key={index} className="flex gap-3 rounded-xl border border-border-col p-3"><div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded-lg bg-background-base">{item.image_url ? <img src={item.image_url} alt="" className="h-full w-full object-cover" /> : <Package size={20} className="text-text-col-tertiary" />}</div><div><p className="font-semibold text-text-col-primary">{item.name} ×{item.qty}</p><p className="mt-1 text-sm text-text-col-tertiary">¥{item.price.toFixed(2)} · {Object.entries(item.attributes).map((entry) => entry[0] + "：" + entry[1]).join(" · ")}</p></div></div>)}</div></section>
        <section className="rounded-2xl border border-border-col bg-background-surface p-5 shadow-sm"><Title icon={<ShieldCheck size={18} />} title="售后申请与 Agent 核验" hint="展示可解释的业务核验结果，不暴露模型内部推理。" /><div className="grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-background-raised p-3"><p className="text-xs text-text-col-tertiary">售后类型</p><p className="mt-1 font-semibold text-text-col-primary">{selected.refund?.after_sales_type || "待确认"}</p></div><div className="rounded-xl bg-background-raised p-3"><p className="text-xs text-text-col-tertiary">退款金额</p><p className="mt-1 font-semibold text-text-col-primary">¥{selected.refund?.refund_amount?.toFixed(2) || "0.00"}</p></div><div className="rounded-xl bg-background-raised p-3"><p className="text-xs text-text-col-tertiary">当前状态</p><p className="mt-1 font-semibold text-text-col-primary">{selected.refund?.status_label || selected.action_label}</p></div></div><div className="mt-4 rounded-xl border border-accent/30 bg-accent/10/60 p-4"><p className="text-sm font-semibold text-accent">用户申请说明</p><p className="mt-2 text-sm leading-6 text-text-col-secondary">{selected.refund?.reason_detail || String(selected.context_snapshot.user_request || "未提供文字说明")}</p></div><div className="mt-4 grid gap-4 md:grid-cols-2"><div><p className="mb-2 text-sm font-semibold text-text-col-primary">已完成核验</p>{selected.agent_checks.map((item, index) => <p key={index} className="mb-2 flex gap-2 text-sm leading-5 text-text-col-secondary"><CheckCircle2 size={16} className="shrink-0 text-success" />{item}</p>)}</div><div><p className="mb-2 text-sm font-semibold text-text-col-primary">规则与转人工原因</p>{selected.policy_checks.map((item, index) => <p key={index} className="mb-2 flex gap-2 text-sm leading-5 text-text-col-secondary"><ShieldCheck size={16} className="shrink-0 text-accent" />{item}</p>)}</div></div></section>
        <section className="rounded-2xl border border-border-col bg-background-surface p-5 shadow-sm"><Title icon={<Paperclip size={18} />} title="用户上传的图片与凭证" hint="“本次补充”表示上一轮要求补充后新增的材料。" /><Attachments items={selected.attachments} /></section>
        <section className="rounded-2xl border border-border-col bg-background-surface p-5 shadow-sm"><Title icon={<MessageCircleMore size={18} />} title="完整对话上下文" hint="含用户描述、店小服答复和审核人员通知。" /><div className="max-h-[520px] space-y-3 overflow-y-auto rounded-xl bg-background-raised p-4">{selected.conversation.filter((item) => item.content.trim()).map((item) => <div key={item.id} className={"flex " + (item.role === "user" ? "justify-end" : "justify-start")}><div className={"max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 " + (item.role === "user" ? "bg-accent text-accent-subtle" : item.message_type === "review_request" ? "border border-warning/30 bg-warning/10 text-warning" : "border border-border-col bg-background-surface text-text-col-secondary")}><p className="whitespace-pre-wrap">{item.content}</p><p className="mt-1 text-[11px] opacity-60">{item.role === "user" ? selected.user?.nickname || "用户" : item.message_type === "review_request" ? "审核人员通知" : "店小服"} · {time(item.created_at)}</p></div></div>)}{!selected.conversation.filter((item) => item.content.trim()).length && <p className="py-6 text-center text-sm text-text-col-tertiary">未读取到文字会话</p>}</div></section>
        <section className="rounded-2xl border border-border-col bg-background-surface p-5 shadow-sm"><Title icon={<Clock3 size={18} />} title="审核历史与操作日志" hint="每一次审核、补充材料和状态变化都会保留，历史不会被覆盖。" /><div className="space-y-4">{selected.operation_log.map((item, index) => <div key={index} className="flex gap-3"><span className={"mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full " + (item.kind === "audit" ? "bg-accent/100" : item.kind === "attachment" ? "bg-accent-light" : "bg-success/100")} /><div><p className="text-sm font-medium text-text-col-primary">{item.title}</p>{item.detail && <p className="mt-0.5 text-sm text-text-col-tertiary">{item.detail}</p>}<p className="mt-1 text-xs text-text-col-tertiary">{time(item.time)}</p></div></div>)}</div></section>
      </div>
      <aside className="h-fit rounded-2xl border border-border-col bg-background-surface p-5 shadow-sm xl:sticky xl:top-6"><Title icon={<FileText size={18} />} title="提交审核结论" hint={selected.action === "PENDING" ? "说明会同步显示在原对话、未读通知和售后记录中。" : "该审核已完成，记录已保留用于追溯。"} />{selected.action === "PENDING" ? <><label className="text-sm font-semibold text-text-col-primary">审核说明</label><textarea rows={7} value={note} onChange={(event) => setNote(event.target.value)} placeholder="例如：请补充商品破损部位、外包装和快递面单的清晰照片。" className="mt-2 w-full resize-none rounded-xl border border-border-col bg-background-raised px-3 py-3 text-sm leading-6 outline-none focus:border-accent focus:bg-background-surface" /><p className="mt-2 text-xs leading-5 text-text-col-tertiary">要求补充材料时请写清楚所需内容。用户上传后，售后将自动重新进入审核队列。</p><div className="mt-5 grid gap-2"><button disabled={!!submitting} onClick={() => void decide("REQUEST_INFO")} className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-2.5 text-sm font-semibold text-warning disabled:opacity-50">{submitting === "REQUEST_INFO" ? "提交中…" : "要求补充材料"}</button><button disabled={!!submitting} onClick={() => void decide("APPROVE")} className="rounded-xl bg-success px-3 py-2.5 text-sm font-semibold text-accent-subtle disabled:opacity-50">{submitting === "APPROVE" ? "提交中…" : "同意申请"}</button><button disabled={!!submitting} onClick={() => void decide("REJECT")} className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2.5 text-sm font-semibold text-danger disabled:opacity-50">{submitting === "REJECT" ? "提交中…" : "拒绝申请"}</button></div></> : <div className="rounded-xl bg-background-raised p-4"><p className="font-semibold text-text-col-primary">{selected.action_label}</p><p className="mt-2 text-sm leading-6 text-text-col-secondary">{selected.admin_comment || "审核说明未填写"}</p><p className="mt-3 text-xs text-text-col-tertiary">{time(selected.reviewed_at)}</p></div>}</aside>
      </div>
    </div>}</main>
  </div>;
}
