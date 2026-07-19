"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ImageUp, MessageSquarePlus, Paperclip, Plus, ShoppingBag, Trash2, X } from "lucide-react";
import { getStoredAuth } from "@/lib/api/auth";
import { sendChatMessage } from "@/lib/api/chat";
import { listMyOrders, listMyRefunds, listNotifications, markAfterSalesNotificationsRead, uploadAttachment } from "@/lib/api/customer";
import { getApiBaseUrl } from "@/lib/api/client";
import { clearSession, loadSession, saveSession } from "@/lib/api/storage";
import { deleteChatSession, getChatSession, listChatSessions, updateChatSession } from "@/lib/api/conversations";
import { toUserMessage } from "@/lib/api/errors";
import type { StoredAuthState } from "@/types/auth";
import type { AttachmentRecord, CustomerOrder, NotificationRecord, RefundRecord } from "@/types/customer";
import type { ChatSessionSummary, PersistedChatMessage } from "@/types/conversation";

interface ProductRecommendation {
  id: string;
  name: string;
  image: string;
  price: number;
  selling_points: string[];
  reason: string;
  colors: string[];
  sizes: string[];
  stock_status: string;
}

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
  order?: CustomerOrder;
  orderPrompt?: boolean;
  attachment?: AttachmentRecord;
  productCards?: ProductRecommendation[];
}

const LOCAL_PRODUCT_IDS = new Set([
  "underwear-ice-silk-brief", "underwear-cotton-antibacterial", "underwear-modal-boxer", "loungewear-soft-knit", "travel-wash-set",
  "tshirt-coolmax-daily", "shirt-commute-oxford", "pants-ice-wideleg", "skirt-a-line-summer", "sunproof-jacket-light",
  "sunproof-hat-upf50", "sunproof-hat-wide-brim", "sunproof-hat-visor-fold", "sneaker-cloud-walk", "backpack-commute-light",
  "bag-summer-crossbody", "bag-canvas-tote", "cup-vacuum-500ml", "earphone-anc-pro", "earphone-open-sport",
  "earphone-lite-commute", "powerbank-slim-10000", "sunscreen-daily-sensitive", "sunscreen-moisture-cream", "sunscreen-oilcontrol-gel",
  "bedding-cotton-set", "towel-soft-cotton", "laundry-detergent-lowfoam",
]);

function productImageSrc(card: ProductRecommendation) {
  if (card.id && LOCAL_PRODUCT_IDS.has(card.id)) return `/product-images/${card.id}.svg`;
  return card.image;
}

function createId(prefix: string) {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${id}`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(value));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function requiresOrder(text: string) {
  const normalized = text.replace(/\s+/g, "").toLowerCase();
  const policyTopic = /七天无理由|7天无理由|退货|退款|换货|取消订单|修改地址|修改收货地址|收货地址|物流|催发货|少件|错发|破损|凭证|运费|运费险|到账|原路退回|发票|优惠券|价保|支付|售后期限|人工审核|平台介入|隐私|数据隔离/;
  const policyQuestion = /定义|是什么|什么意思|怎么理解|政策|规则|条件|标准|范围|流程|时效|期限|多少天|几天|多久|什么时候|如何|怎么|能否|是否|可以吗|支持吗|适用|不适用|哪些|包含|区别|怎么算|谁承担|需要什么/;
  const execution = /帮我申请|替我申请|给我申请|我要申请|现在申请|直接申请|确认申请|帮我取消|我要取消|直接取消|确认取消|帮我修改|我要修改|直接修改|确认修改|帮我退款|我要退款|直接退款|确认退款|提交退款|提交售后|这个订单|这笔订单|订单号|sc0|sn0/i;
  if (policyTopic.test(normalized) && policyQuestion.test(normalized) && !execution.test(normalized)) return false;
  return /(我要|申请|办理|帮我|修改|取消|查|看).*(订单|商品|物流|快递|退款|退货|换货|售后|地址)|物流|快递|退款|退货|换货|售后|发货|签收|SC\d+|SN\d+/i.test(text);
}

const PRODUCT_CARD_PATTERN = /\n?\s*\[\[PRODUCT_CARDS:([\s\S]*?)\]\]\s*/;

function extractProductCards(text: string): ProductRecommendation[] {
  const match = text.match(PRODUCT_CARD_PATTERN);
  if (!match) return [];
  try {
    const parsed = JSON.parse(match[1]) as ProductRecommendation[] | { items?: ProductRecommendation[] };
    const items = Array.isArray(parsed) ? parsed : parsed.items;
    return Array.isArray(items) ? items.filter((item) => item?.name && item?.image).map((item) => ({ ...item, image: productImageSrc(item) })) : [];
  } catch {
    return [];
  }
}

function stripProductCards(text: string) {
  return text
    .replace(PRODUCT_CARD_PATTERN, "")
    .replace(/\n?\s*\[\[PRODUCT_CARDS:[\s\S]*$/g, "")
    .trim();
}


function cleanAssistantText(text: string) {
  return stripProductCards(text)
    .split("\n")
    .filter((line) => !/风险等级|触发原因|工具|调用参数|数据库字段|thread|session/i.test(line))
    .join("\n")
    .replace(/您的退货申请需要人工审核/g, "这笔申请需要人工再核实一下")
    .replace(/已选择订单[^。]*。?/g, "")
    .replace(/请描述售后诉求。?/g, "")
    .trim();
}


function ProductRecommendationCards({ cards, onAction }: { cards: ProductRecommendation[]; onAction: (text: string) => void }) {
  if (!cards.length) return null;
  return (
    <div className="mt-3 grid w-full gap-3 md:grid-cols-2 xl:grid-cols-3">
      {cards.map((card) => (
        <div key={card.id || card.name} className="overflow-hidden rounded border border-border-col bg-background-surface text-left">
          <div className="relative aspect-[4/3] w-full overflow-hidden bg-background-raised">
            <div className="absolute inset-0 flex items-center justify-center bg-background-raised text-xs text-text-col-tertiary">商品图</div>
            <img
              src={productImageSrc(card)}
              alt=""
              className="relative h-full w-full object-cover"
              onError={(event) => { event.currentTarget.style.display = "none"; }}
            />
          </div>
          <div className="p-3">
            <div className="flex items-start justify-between gap-3">
              <p className="min-w-0 text-sm font-semibold text-text-col-primary">{card.name}</p>
              <span className="shrink-0 text-sm font-semibold text-accent">¥{Number(card.price).toFixed(0)}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-text-col-secondary">{card.reason}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(card.selling_points || []).slice(0, 3).map((point) => <span key={point} className="rounded bg-background-raised px-2 py-1 text-[11px] text-text-col-secondary">{point}</span>)}
            </div>
            <div className="mt-3 space-y-1 text-xs text-text-col-tertiary">
              <p>颜色：{(card.colors || []).join(" / ") || "以页面可选为准"}</p>
              <p>尺码：{(card.sizes || []).join(" / ") || "以页面可选为准"}</p>
              <p>库存：{card.stock_status || "可咨询库存"}</p>
            </div>
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => onAction(`查看详情：${card.name}`)} className="flex-1 rounded border border-border-col px-2.5 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">查看详情</button>
              <button type="button" onClick={() => onAction(`选择规格：${card.name}`)} className="flex-1 rounded bg-accent px-2.5 py-1.5 text-xs font-semibold text-accent-subtle transition-opacity hover:opacity-90">选择规格</button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}


function attachmentUrl(url?: string | null) {
  if (!url) return "";
  if (/^https?:/.test(url)) return url;
  return `${getApiBaseUrl()}${url}`;
}

function AttachmentCard({ attachment }: { attachment: AttachmentRecord }) {
  return (
    <div className="w-full max-w-md rounded border border-border-col bg-background-surface p-3">
      <div className="flex gap-3">
        {attachment.url ? <img src={attachmentUrl(attachment.url)} alt="" className="h-20 w-20 rounded object-cover" /> : <div className="flex h-20 w-20 items-center justify-center rounded border border-border-col bg-background-raised text-xs text-text-col-tertiary">凭证</div>}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text-col-primary">{attachment.attachment_type === "evidence" ? "售后凭证" : "图片附件"}</p>
          <p className="mt-1 truncate text-xs text-text-col-tertiary">{attachment.filename || "已上传凭证"}</p>
          {attachment.order_sn && <p className="mt-1 text-xs text-text-col-tertiary">关联订单 {attachment.order_sn}</p>}
          <p className="mt-2 text-xs text-accent">已保存到当前咨询</p>
        </div>
      </div>
    </div>
  );
}

const ACTIVE_AFTER_SALES_STATES = new Set([
  "pending_user_confirm", "submitted", "waiting_evidence", "pending_review", "approved",
  "waiting_return", "return_in_transit", "merchant_received", "refund_processing",
]);

function AfterSalesProgressCard({ record }: { record: RefundRecord }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-3 rounded border border-accent/30 bg-accent/10 px-3 py-2 text-xs">
      <div className="min-w-0">
        <p className="truncate font-medium text-text-col-primary">售后 #{record.after_sales_id} · {record.after_sales_status_label}</p>
        {record.admin_note && <p className="mt-0.5 truncate text-text-col-tertiary">{record.admin_note}</p>}
      </div>
      <Link href="/after-sales" className="shrink-0 text-accent hover:text-accent-light">查看详情</Link>
    </div>
  );
}

function manualConfirmText(content: string) {
  if (/商品异常|商品问题|照片|凭证/.test(content)) return "继续申请，商品问题需要核验证据，照片凭证已补充";
  if (/换货期限|自动换货|不能直接自动换货/.test(content)) return "继续申请，超过平台换货期限";
  if (/仅退款处理期限|自动仅退款/.test(content)) return "继续申请，超过自动仅退款处理期限";
  if (/超过签收后 7 天|超过七天|7 天/.test(content)) return "继续申请，超过七天无理由期限";
  if (/退款金额|自动审批范围/.test(content)) return "继续申请，退款金额超过自动审批范围";
  if (/运输中|没有签收|尚未签收/.test(content)) return "继续申请，订单尚未签收";
  if (/近期售后申请/.test(content)) return "继续申请，当前账号近期售后申请较多";
  if (/已使用|拆封|二次销售/.test(content)) return "继续申请，商品可能已使用影响二次销售";
  return "继续申请";
}

function manualAuditCard(content: string) {
  const lines = content.split("\n").map((line) => line.trim()).filter(Boolean);
  const start = lines.findIndex((line) => line === "人工核实中");
  if (start === -1) return null;
  const read = (prefix: string) => lines.find((line) => line.startsWith(prefix))?.replace(prefix, "") || "";
  return {
    reason: read("原因："),
    status: read("当前状态：") || "等待审核",
    eta: read("预计处理：") || "1 个工作日内",
    auditId: read("审核编号："),
  };
}

function stripManualAuditCard(content: string) {
  const lines = content.split("\n");
  const start = lines.findIndex((line) => line.trim() === "人工核实中");
  return (start === -1 ? content : lines.slice(0, start).join("\n")).trim();
}

function ManualAuditStatusCard({ content }: { content: string }) {
  const card = manualAuditCard(content);
  if (!card) return null;
  return (
    <div className="mt-3 w-full max-w-md rounded border border-accent/30 bg-accent/10 p-3 text-sm">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="font-semibold text-text-col-primary">人工核实中</p>
        <span className="rounded bg-background-surface px-2 py-1 text-xs text-accent">{card.status}</span>
      </div>
      <div className="space-y-1 text-xs text-text-col-secondary">
        <p>原因：{card.reason || "等待审核人员核实"}</p>
        <p>预计处理：{card.eta}</p>
        {card.auditId && <p>{card.auditId}</p>}
      </div>
      <Link href="/after-sales" className="mt-3 inline-flex rounded border border-border-col px-2.5 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">查看售后进度</Link>
    </div>
  );
}

function AssistantContent({ content, isStreaming, productCards = [], onAction }: { content: string; isStreaming?: boolean; productCards?: ProductRecommendation[]; onAction: (text: string) => void }) {
  const displayContent = stripManualAuditCard(content || (isStreaming ? "​" : "..."));
  const showManualActions = !isStreaming && content.includes("还要继续申请吗？");
  const showOrderSwitchActions = !isStreaming && content.includes("确认更换订单吗？");
  const showFlowSwitchActions = !isStreaming && content.includes("确认切换吗？");
  return (
    <>
      {displayContent && (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p className="mb-2 last:mb-0 text-text-col-secondary">{children}</p>,
            ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-4 text-text-col-secondary">{children}</ul>,
            ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-4 text-text-col-secondary">{children}</ol>,
            strong: ({ children }) => <strong className="font-semibold text-text-col-primary">{children}</strong>,
          }}
        >
          {displayContent}
        </ReactMarkdown>
      )}
      {showManualActions && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => onAction(manualConfirmText(content))} className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-subtle transition-opacity hover:opacity-90">继续申请</button>
          <button type="button" onClick={() => onAction("暂不申请")} className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">暂不申请</button>
        </div>
      )}
      {showOrderSwitchActions && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => onAction("确认更换订单")} className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-subtle transition-opacity hover:opacity-90">确认更换</button>
          <button type="button" onClick={() => onAction("暂不更换")} className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">暂不更换</button>
        </div>
      )}
      {showFlowSwitchActions && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => onAction("确认切换")} className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-subtle transition-opacity hover:opacity-90">确认切换</button>
          <button type="button" onClick={() => onAction("暂不切换")} className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">暂不切换</button>
        </div>
      )}
      {!isStreaming && productCards.length > 0 && <ProductRecommendationCards cards={productCards} onAction={onAction} />}
      <ManualAuditStatusCard content={content} />
    </>
  );
}

function orderFromCard(data: PersistedChatMessage["card_data"]): CustomerOrder | null {
  if (!data?.order_sn) return null;
  return {
    id: Number(data.id || 0),
    order_sn: String(data.order_sn),
    product_name: String(data.product_name || "订单商品"),
    product_image: data.product_image || null,
    total_amount: Number(data.total_amount || 0),
    status: String(data.status || ""),
    status_label: String(data.status_label || data.status || ""),
    tracking_number: data.tracking_number || null,
    shipping_address: String(data.shipping_address || ""),
    created_at: String(data.created_at || new Date().toISOString()),
    items: [],
  };
}

function OrderThumb({ order }: { order: CustomerOrder }) {
  if (order.product_image) return <img src={order.product_image} alt="" className="h-14 w-14 rounded object-cover" />;
  return <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded border border-border-col bg-background-raised text-lg font-semibold text-accent">{(order.product_name || "商").slice(0, 1)}</div>;
}

function orderActions(order: CustomerOrder, afterSales?: RefundRecord) {
  const afterSalesState = afterSales?.after_sales_status || "";
  if (ACTIVE_AFTER_SALES_STATES.has(afterSalesState)) {
    if (afterSalesState === "waiting_evidence") return ["补充凭证", "查看进度", "撤销申请"];
    return ["查看进度", "撤销申请"];
  }
  if (afterSalesState === "completed" || order.status === "REFUNDED") return ["查看商品"];
  if ((afterSalesState === "cancelled" || afterSalesState === "rejected") && order.status === "DELIVERED") {
    return ["重新申请售后", "查看商品"];
  }
  if (order.status === "PAID" || order.status === "PENDING") return ["修改地址", "取消订单", "催发货"];
  if (order.status === "SHIPPED") return ["查看物流", "催物流", "申请拦截"];
  if (order.status === "INTERCEPTING") return ["查看拦截进度", "查看物流"];
  if (order.status === "DELIVERED") return ["申请售后", "换货", "查看商品"];
  if (order.status === "REFUNDING") return ["查看进度", "补充凭证", "撤销申请"];
  return ["查看商品"];
}

function OrderCard({ order, afterSales, onChoose, prompt, onAction, compact = false }: { order: CustomerOrder; afterSales?: RefundRecord; onChoose?: () => void; prompt?: boolean; onAction?: (text: string) => void; compact?: boolean }) {
  const actions = orderActions(order, afterSales).slice(0, 3);
  const displayStatus = afterSales?.after_sales_status === "completed" ? "已退款" : order.status_label;
  return (
    <div className={`w-full rounded border border-border-col bg-background-surface p-3 text-left ${compact ? "" : "max-w-md"}`}>
      {prompt && <p className="mb-3 text-sm font-medium text-text-col-primary">您咨询的是这个订单吗？</p>}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 gap-3">
          <OrderThumb order={order} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-text-col-primary">{order.product_name || "订单商品"}</p>
            <p className="mt-1 text-xs text-text-col-tertiary">订单号 {order.order_sn}</p>
            <p className="mt-1 text-xs text-text-col-tertiary">{formatDate(order.created_at)}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center justify-between gap-3 sm:min-w-44 sm:justify-end">
          <span className="rounded border border-border-col px-2 py-1 text-xs text-text-col-secondary">{displayStatus}</span>
          <span className="font-semibold text-accent">¥{order.total_amount}</span>
        </div>
      </div>
      {onChoose ? <div className="mt-3 flex justify-end"><button onClick={onChoose} className="w-full rounded bg-accent px-3 py-2 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90 sm:w-40">{prompt ? "确认此订单" : "选择此订单"}</button></div> : null}
      {!prompt && !onChoose && onAction ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map((action) => (
            <button key={action} onClick={() => onAction(action)} className="rounded border border-border-col px-2.5 py-1.5 text-xs text-text-col-secondary hover:border-accent hover:text-accent">{action}</button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function OrdersModal({ orders, afterSales, onClose, onChoose }: { orders: CustomerOrder[]; afterSales: RefundRecord[]; onClose: () => void; onChoose: (order: CustomerOrder) => void }) {
  return (
    <div className="absolute inset-0 z-40 flex items-end justify-center bg-background-base/70 p-4 backdrop-blur-sm md:items-center">
      <div className="max-h-[82vh] w-full max-w-5xl overflow-hidden rounded border border-border-col bg-background-surface shadow-2xl shadow-black/30">
        <div className="flex items-center justify-between border-b border-border-col px-5 py-4">
          <div><p className="text-xs font-mono text-accent">我的订单</p><h2 className="mt-1 text-lg font-semibold text-text-col-primary">选择本次咨询的订单</h2></div>
          <button onClick={onClose} className="rounded border border-border-col p-2 text-text-col-tertiary transition-colors hover:border-accent hover:text-accent" aria-label="关闭"><X size={16} /></button>
        </div>
        <div className="grid max-h-[62vh] gap-3 overflow-y-auto p-6">
          {orders.map((order) => <OrderCard key={order.order_sn} order={order} afterSales={afterSales.find((record) => record.order_sn === order.order_sn)} compact onChoose={() => onChoose(order)} />)}
          {orders.length === 0 && <p className="p-6 text-center text-sm text-text-col-tertiary">当前账号暂无可选订单。</p>}
        </div>
      </div>
    </div>
  );
}

export default function ChatInterface() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [auth, setAuth] = useState<StoredAuthState | null>(null);
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [afterSales, setAfterSales] = useState<RefundRecord[]>([]);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [boundOrder, setBoundOrder] = useState<CustomerOrder | null>(null);
  const [pendingOrderSwitch, setPendingOrderSwitch] = useState<CustomerOrder | null>(null);
  const [showOrders, setShowOrders] = useState(false);
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTypeRef = useRef<"image" | "evidence">("image");

  const title = useMemo(() => boundOrder ? `${boundOrder.product_name || "订单商品"} 售后咨询` : "售后咨询", [boundOrder]);
  const unreadCount = notifications.filter((item) => !item.is_read && item.target_type === "after_sales").length;
  const latestBoundAfterSales = useMemo(() => afterSales.find((item) => item.order_sn === boundOrder?.order_sn), [afterSales, boundOrder]);
  const currentAfterSales = useMemo(
    () => afterSales.find((item) => item.order_sn === boundOrder?.order_sn && ACTIVE_AFTER_SALES_STATES.has(item.after_sales_status)),
    [afterSales, boundOrder],
  );
  const currentOrderStatus = latestBoundAfterSales?.after_sales_status === "completed" ? "已退款" : (boundOrder?.status_label || boundOrder?.status || "");

  const refreshSessions = async () => setSessions(await listChatSessions());

  const acknowledgeAfterSales = () => {
    setNotifications((items) => items.map((item) => item.target_type === "after_sales" ? { ...item, is_read: true } : item));
    void markAfterSalesNotificationsRead().catch(() => void listNotifications().then(setNotifications));
  };

  const ensureThread = async () => {
    if (!auth) throw new Error("AUTH_REQUIRED");
    if (threadId && sessionId) return { thread: threadId, session: sessionId };
    const stored = loadSession(String(auth.user.user_id));
    const nextThread = stored?.thread_id || createId("thread");
    const nextSession = stored?.session_id || createId("session");
    setThreadId(nextThread);
    setSessionId(nextSession);
    saveSession({ thread_id: nextThread, session_id: nextSession, customer_id: String(auth.user.user_id), updated_at: new Date().toISOString() });
    return { thread: nextThread, session: nextSession };
  };

  const mapPersistedMessages = (items: PersistedChatMessage[]): Message[] => items.map((item) => {
    if (item.message_type === "order_card") return { role: "system", content: "", order: orderFromCard(item.card_data) || undefined };
    if (item.message_type === "attachment_card" && item.card_data) return { role: "system", content: "", attachment: item.card_data as AttachmentRecord };
    return { role: item.role === "user" ? "user" : "assistant", content: cleanAssistantText(item.content), productCards: extractProductCards(item.content) };
  });

  const openSession = async (nextThreadId: string) => {
    if (!auth) return;
    const detail = await getChatSession(nextThreadId);
    setThreadId(detail.thread_id);
    const nextSessionId = createId("session");
    setSessionId(nextSessionId);
    saveSession({ thread_id: detail.thread_id, session_id: nextSessionId, customer_id: String(auth.user.user_id), updated_at: new Date().toISOString() });
    setMessages(mapPersistedMessages(detail.messages));
    const selected = detail.order_sn ? orders.find((order) => order.order_sn === detail.order_sn) : null;
    setBoundOrder(selected || null);
  };

  useEffect(() => {
    const stored = getStoredAuth();
    if (!stored) { router.replace("/login?next=/chat"); return; }
    if (stored.user?.is_admin) { router.replace("/admin"); return; }
    setAuth(stored);
    Promise.all([listMyOrders(), listChatSessions(), listMyRefunds(), listNotifications()]).then(([nextOrders, nextSessions, nextAfterSales, nextNotifications]) => {
      setOrders(nextOrders);
      setSessions(nextSessions);
      setAfterSales(nextAfterSales);
      setNotifications(nextNotifications);
      const storedSession = loadSession(String(stored.user.user_id));
      if (storedSession) { setSessionId(storedSession.session_id); setThreadId(storedSession.thread_id); }
      const orderSn = searchParams.get("order")?.toUpperCase();
      const selected = nextOrders.find((order) => order.order_sn === orderSn);
      if (selected) void bindOrder(selected, true, false);
    }).catch(() => { setOrders([]); setSessions([]); });
  }, [router, searchParams]);

  useEffect(() => {
    if (!auth || !threadId) return;
    const configured = process.env.NEXT_PUBLIC_WS_BASE_URL || "ws://localhost:18001";
    const websocketBase = configured.endsWith("/") ? configured.slice(0, -1) : configured;
    const socket = new WebSocket(websocketBase + "/api/v1/ws/" + encodeURIComponent(threadId) + "?token=" + encodeURIComponent(auth.token));
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "after_sales_updated") {
          void listMyRefunds().then(setAfterSales);
          void listNotifications().then(setNotifications);
        }
        if (data.type === "status_change") {
          void listMyOrders().then((nextOrders) => {
            setOrders(nextOrders);
            setBoundOrder((current) => current
              ? nextOrders.find((order) => order.order_sn === current.order_sn) || current
              : current);
          });
          void listNotifications().then(setNotifications);
        }
      } catch {}
    };
    const heartbeat = window.setInterval(() => { if (socket.readyState === WebSocket.OPEN) socket.send("ping"); }, 25000);
    return () => { window.clearInterval(heartbeat); socket.close(); };
  }, [auth, threadId]);

  useEffect(() => {
    if (!auth) return;
    const timer = window.setInterval(() => {
      listMyOrders().then((nextOrders) => {
        setOrders(nextOrders);
        setBoundOrder((current) => current
          ? nextOrders.find((order) => order.order_sn === current.order_sn) || current
          : current);
      }).catch(() => undefined);
      listMyRefunds().then(setAfterSales).catch(() => undefined);
      listNotifications().then(setNotifications).catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [auth]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const hasLocalUnsubmittedFlow = () => {
    const lastAssistant = [...messages].reverse().find((item) => item.role === "assistant")?.content || "";
    return /确认|新地址|上传|补充|原因|规格|颜色|尺码|物流单号|寄回|还要继续申请|申请还没有正式提交|等待你/.test(lastAssistant);
  };

  const bindOrder = async (order: CustomerOrder, addCard = true, persistCard = true, force = false) => {
    if (!force && boundOrder && boundOrder.order_sn !== order.order_sn && hasLocalUnsubmittedFlow()) {
      setPendingOrderSwitch(order);
      setShowOrders(false);
      setMessages((prev) => [...prev, { role: "assistant", content: "当前还有未提交的处理流程。更换订单后，前面已经填写的原因、地址或凭证可能不会继续沿用。确认更换订单吗？" }]);
      return;
    }
    setPendingOrderSwitch(null);
    setBoundOrder(order);
    setShowOrders(false);
    const ids = await ensureThread();
    if (addCard) setMessages((prev) => [...prev, { role: "system", content: "", order }]);
    if (persistCard) {
      await updateChatSession(ids.thread, { order_sn: order.order_sn, add_order_card: addCard });
      await refreshSessions();
    }
  };

  const startNew = async () => {
    abortRef.current?.abort();
    if (auth) clearSession(String(auth.user.user_id));
    const nextThread = createId("thread");
    const nextSession = createId("session");
    setSessionId(nextSession);
    setThreadId(nextThread);
    setBoundOrder(null);
    setPendingOrderSwitch(null);
    setMessages([]);
    setInput("");
    if (auth) saveSession({ thread_id: nextThread, session_id: nextSession, customer_id: String(auth.user.user_id), updated_at: new Date().toISOString() });
  };

  const removeSession = async (targetThread: string) => {
    await deleteChatSession(targetThread);
    if (targetThread === threadId) await startNew();
    await refreshSessions();
  };


  const handleUpload = async (file: File | undefined) => {
    if (!file || !auth) return;
    const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
    if (file.size <= 0) {
      setMessages((prev) => [...prev, { role: "assistant", content: "这个文件是空的，重新选一张图片再上传吧。" }]);
      return;
    }
    if (!allowedTypes.has(file.type)) {
      setMessages((prev) => [...prev, { role: "assistant", content: "目前只能上传 JPG、PNG、WEBP 或 GIF 图片。换个格式再试一下。" }]);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setMessages((prev) => [...prev, { role: "assistant", content: "这张图片超过 5MB 了。压缩后再上传，我会继续接着这笔售后处理。" }]);
      return;
    }
    const ids = await ensureThread();
    try {
      const attachment = await uploadAttachment({ file, threadId: ids.thread, orderSn: boundOrder?.order_sn, attachmentType: uploadTypeRef.current });
      setMessages((prev) => [...prev, { role: "system", content: "", attachment }]);
      if (uploadTypeRef.current === "evidence") {
        void sendMessage("照片凭证已补充，请继续判断");
      }
    } catch (error) {
      setMessages((prev) => [...prev, { role: "assistant", content: toUserMessage(error) }]);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const chooseUpload = (type: "image" | "evidence") => {
    uploadTypeRef.current = type;
    setShowAttachMenu(false);
    fileInputRef.current?.click();
  };

  const sendMessage = async (text: string, orderOverride?: CustomerOrder) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    if (!auth) { router.replace("/login?next=/chat"); return; }

    if (trimmed === "确认更换订单" && pendingOrderSwitch) {
      const nextOrder = pendingOrderSwitch;
      setPendingOrderSwitch(null);
      setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
      await bindOrder(nextOrder, true, true, true);
      return;
    }
    if (trimmed === "暂不更换" && pendingOrderSwitch) {
      setPendingOrderSwitch(null);
      setMessages((prev) => [...prev, { role: "user", content: trimmed }, { role: "assistant", content: "好的，先保留当前订单。你可以继续把这笔订单的问题发给我。" }]);
      return;
    }

    const ids = await ensureThread();
    const effectiveOrder = orderOverride || boundOrder;
    if (orderOverride && boundOrder?.order_sn !== orderOverride.order_sn) setBoundOrder(orderOverride);

    if (!effectiveOrder && requiresOrder(trimmed)) {
      const mentioned = trimmed.match(/(?:SN|SC)\d+/i)?.[0]?.toUpperCase();
      const matched = mentioned ? orders.find((order) => order.order_sn === mentioned) : null;
      setMessages((prev) => [...prev, { role: "user", content: trimmed }, matched ? { role: "assistant", content: "", order: matched, orderPrompt: true } : { role: "assistant", content: "我先帮你定位一下是哪笔订单。请从订单列表里选一下，确认后我会接着处理你的问题。" }]);
      setInput("");
      if (!matched) setShowOrders(true);
      return;
    }

    setMessages((prev) => [...prev, { role: "user", content: trimmed }, { role: "assistant", content: "", isStreaming: true }]);
    setInput("");
    setLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let fullContent = "";

    try {
      const result = await sendChatMessage({
        message: trimmed,
        sessionId: ids.session,
        threadId: ids.thread,
        customerId: String(auth.user.user_id),
        orderSn: effectiveOrder?.order_sn,
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "message") {
            fullContent += event.content;
            setMessages((prev) => { const updated = [...prev]; updated[updated.length - 1] = { role: "assistant", content: cleanAssistantText(fullContent), isStreaming: true }; return updated; });
          } else if (event.type === "final") {
            const rawContent = event.content || fullContent;
            const content = cleanAssistantText(rawContent);
            const productCards = extractProductCards(rawContent);
            setMessages((prev) => { const updated = [...prev]; updated[updated.length - 1] = { role: "assistant", content, productCards, isStreaming: false }; return updated; });
          }
        },
      });
      setSessionId(result.session_id);
      setThreadId(result.thread_id);
      if (effectiveOrder) {
        const [nextOrders, nextAfterSales] = await Promise.all([listMyOrders(), listMyRefunds()]);
        setOrders(nextOrders);
        setAfterSales(nextAfterSales);
        const refreshed = nextOrders.find((order) => order.order_sn === effectiveOrder.order_sn);
        if (refreshed) setBoundOrder(refreshed);
      }
      await refreshSessions();
    } catch (error) {
      const message = toUserMessage(error);
      setMessages((prev) => { const updated = [...prev]; updated[updated.length - 1] = { role: "assistant", content: message, isStreaming: false }; return updated; });
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  };

  return (
    <div className="relative flex flex-1 overflow-hidden bg-background-base">
      <aside className="hidden w-64 shrink-0 border-r border-border-col bg-background-surface md:flex md:flex-col">
        <div className="flex items-center justify-between border-b border-border-col px-4 py-3">
          <p className="text-sm font-semibold text-text-col-primary">历史咨询</p>
          <button onClick={() => void startNew()} className="rounded border border-border-col p-1.5 text-text-col-tertiary hover:border-accent hover:text-accent" aria-label="新建咨询"><MessageSquarePlus size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {sessions.map((item) => (
            <div key={item.thread_id} className={`group mb-1 flex items-center gap-1 rounded border px-2 py-2 ${item.thread_id === threadId ? "border-accent/30 bg-accent/10" : "border-transparent hover:bg-background-raised"}`}>
              <button onClick={() => void openSession(item.thread_id)} className="min-w-0 flex-1 text-left">
                <p className="truncate text-sm text-text-col-primary">{item.title}</p>
                <p className="mt-1 text-xs text-text-col-tertiary">{formatTime(item.updated_at)}</p>
              </button>
              <button onClick={() => void removeSession(item.thread_id)} className="opacity-0 rounded p-1 text-text-col-tertiary hover:text-danger group-hover:opacity-100" aria-label="删除"><Trash2 size={14} /></button>
            </div>
          ))}
          {sessions.length === 0 && <p className="px-3 py-8 text-center text-sm text-text-col-tertiary">暂无历史咨询</p>}
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="border-b border-border-col bg-background-surface px-6 py-3">
          <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3">
            <div><p className="text-sm font-semibold text-text-col-primary">店小服 ShopCare</p><p className="mt-0.5 text-xs text-text-col-tertiary">{title}</p></div>
            <div className="flex flex-wrap items-center gap-2">
              <Link href="/orders" className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">我的订单</Link>
              <Link href="/after-sales" onClick={acknowledgeAfterSales} className="relative rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">售后记录{unreadCount > 0 && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-danger" />}</Link>
              <button onClick={() => void startNew()} className="rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">新建咨询</button>
              <Link href="/profile" className="rounded bg-background-raised px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:text-accent">{auth?.user?.full_name || "个人中心"}</Link>
            </div>
          </div>
        </div>

        <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col overflow-hidden">
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-6">
            {messages.length === 0 && (
              <div className="py-20 text-center text-text-col-tertiary">
                <p className="font-display text-lg font-semibold text-text-col-primary">你好，我是店小服</p>
                <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed">我是 AI 售后助手。你可以直接说想查物流、改地址、退款，或者先选择一笔订单。</p>
              </div>
            )}
            {messages.map((msg, index) => (
              <div key={index} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role !== "user" && !msg.order && <div className="mr-2 mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded bg-accent text-xs font-bold text-accent-subtle">店</div>}
                {msg.order ? <OrderCard order={msg.order} afterSales={afterSales.find((record) => record.order_sn === msg.order?.order_sn)} prompt={msg.orderPrompt} onChoose={msg.orderPrompt ? () => void bindOrder(msg.order as CustomerOrder) : undefined} onAction={(action) => void sendMessage(action, msg.order as CustomerOrder)} /> : msg.attachment ? <AttachmentCard attachment={msg.attachment} /> : (
                  <div className={`max-w-[75%] rounded px-4 py-3 text-sm leading-relaxed ${msg.role === "user" ? "bg-accent font-medium text-accent-subtle whitespace-pre-wrap" : `border border-border-col bg-background-surface text-text-col-primary ${msg.isStreaming ? "cursor-blink" : ""}`}`}>
                    {msg.role === "user" ? msg.content : <AssistantContent content={msg.content} isStreaming={msg.isStreaming} productCards={msg.productCards} onAction={(action) => void sendMessage(action)} />}
                  </div>
                )}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-border-col bg-background-surface px-6 py-4">
            {currentAfterSales && <AfterSalesProgressCard record={currentAfterSales} />}
            {boundOrder && <div className="mb-3 flex items-center justify-between rounded border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-accent"><span>当前订单：{boundOrder.product_name || "订单商品"} · {boundOrder.order_sn} · {currentOrderStatus}</span><button onClick={() => setShowOrders(true)} className="text-accent-light hover:text-accent">更换</button></div>}
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(event) => void handleUpload(event.target.files?.[0])} />
            <form onSubmit={(event) => { event.preventDefault(); void sendMessage(input); }} className="flex items-center gap-2">
              <div className="relative">
                <button type="button" onClick={() => setShowAttachMenu((value) => !value)} className="rounded border border-border-col bg-background-raised p-2.5 text-text-col-tertiary transition-colors hover:border-accent hover:text-accent" aria-label="添加内容"><Plus size={18} /></button>
                {showAttachMenu && <div className="absolute bottom-12 left-0 z-30 w-44 overflow-hidden rounded border border-border-col bg-background-surface shadow-2xl shadow-black/30"><button type="button" onClick={() => { setShowAttachMenu(false); setShowOrders(true); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-accent"><ShoppingBag size={15} />选择订单</button><button type="button" onClick={() => chooseUpload("image")} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-accent"><ImageUp size={15} />上传图片</button><button type="button" onClick={() => chooseUpload("evidence")} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-accent"><Paperclip size={15} />上传售后凭证</button></div>}
              </div>
              <input type="text" value={input} onChange={(event) => setInput(event.target.value)} placeholder="告诉店小服你想处理什么..." disabled={loading || !auth} className="flex-1 rounded border border-border-col bg-background-raised px-4 py-2.5 text-sm text-text-col-primary outline-none transition-colors placeholder:text-text-col-tertiary focus:border-accent disabled:opacity-50" />
              <button type="submit" disabled={loading || !auth || !input.trim()} className="rounded bg-accent px-4 py-2.5 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40">{loading ? "..." : "发送"}</button>
            </form>
          </div>
        </div>
        {showOrders && <OrdersModal orders={orders} afterSales={afterSales} onClose={() => setShowOrders(false)} onChoose={(order) => void bindOrder(order)} />}
      </div>
    </div>
  );
}
