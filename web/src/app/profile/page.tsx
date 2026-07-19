"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { LogOut, MessageSquareText, PackageSearch, ReceiptText, ShieldCheck, UserRound } from "lucide-react";
import { getCurrentUser, getStoredAuth, logout } from "@/lib/api/auth";
import { listMyOrders, listMyRefunds, restoreDemoData } from "@/lib/api/customer";
import { toUserMessage } from "@/lib/api/errors";
import type { CurrentUserResponse } from "@/types/auth";
import type { CustomerOrder, RefundRecord } from "@/types/customer";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

function StatCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded border border-border-col bg-background-surface px-4 py-3">
      <p className="text-xs text-text-col-tertiary">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-text-col-primary">{value}</p>
      <p className="mt-1 text-xs text-text-col-tertiary">{detail}</p>
    </div>
  );
}

export default function ProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [refunds, setRefunds] = useState<RefundRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const stored = getStoredAuth();
    if (!stored) {
      router.replace("/login?next=/profile");
      return;
    }
    if (stored.user.is_admin) {
      router.replace("/admin");
      return;
    }

    Promise.all([getCurrentUser(), listMyOrders(), listMyRefunds()])
      .then(([nextUser, nextOrders, nextRefunds]) => {
        setUser(nextUser);
        setOrders(nextOrders);
        setRefunds(nextRefunds);
      })
      .catch((err) => setError(toUserMessage(err)))
      .finally(() => setLoading(false));
  }, [router]);

  const activeRefunds = useMemo(
    () => refunds.filter((record) => ["PENDING", "NEED_INFO", "APPROVED", "PROCESSING"].includes(record.status)).length,
    [refunds]
  );
  const latestOrder = orders[0];
  const latestRefund = refunds[0];

  const restoreExperienceData = async () => {
    setError("");
    try {
      const nextOrders = await restoreDemoData();
      const nextRefunds = await listMyRefunds();
      setOrders(nextOrders);
      setRefunds(nextRefunds);
    } catch (err) {
      setError(toUserMessage(err));
    }
  };

  const signOut = () => {
    logout();
    window.location.assign("/");
  };

  return (
    <div className="flex flex-1 overflow-y-auto bg-background-base px-6 py-8">
      <main className="mx-auto w-full max-w-6xl">
        <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-mono text-accent">个人中心</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-text-col-primary">我的 ShopCare</h1>
            <p className="mt-2 text-sm text-text-col-tertiary">管理账号、订单和售后进度。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/chat" className="inline-flex items-center gap-2 rounded bg-accent px-4 py-2 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90">
              <MessageSquareText size={16} /> 开始售后咨询
            </Link>
            <button onClick={restoreExperienceData} className="inline-flex items-center gap-2 rounded border border-border-col px-4 py-2 text-sm text-text-col-secondary transition-colors hover:border-accent hover:text-accent">
              恢复体验数据
            </button>
            <button onClick={signOut} className="inline-flex items-center gap-2 rounded border border-border-col px-4 py-2 text-sm text-text-col-secondary transition-colors hover:border-danger hover:text-danger">
              <LogOut size={16} /> 退出登录
            </button>
          </div>
        </div>

        {error && <p className="mb-4 rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</p>}

        {loading ? (
          <p className="rounded border border-border-col bg-background-surface p-6 text-sm text-text-col-tertiary">正在读取个人中心...</p>
        ) : user ? (
          <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
            <section className="rounded border border-border-col bg-background-surface p-5">
              <div className="flex items-center gap-4">
                <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded bg-accent text-3xl font-bold text-accent-subtle">
                  {(user.full_name || user.username).slice(0, 1)}
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-2xl font-semibold text-text-col-primary">{user.full_name}</h2>
                  <p className="mt-1 font-mono text-sm text-accent">{user.username}</p>
                </div>
              </div>

              <dl className="mt-6 grid gap-3 text-sm">
                <div className="rounded border border-border-col bg-background-base px-3 py-2">
                  <dt className="text-text-col-tertiary">账号状态</dt>
                  <dd className="mt-1 inline-flex items-center gap-1.5 text-success"><ShieldCheck size={15} /> 已登录</dd>
                </div>
                <div className="rounded border border-border-col bg-background-base px-3 py-2">
                  <dt className="text-text-col-tertiary">注册时间</dt>
                  <dd className="mt-1 text-text-col-primary">{formatDate(user.created_at)}</dd>
                </div>
                <div className="rounded border border-border-col bg-background-base px-3 py-2">
                  <dt className="text-text-col-tertiary">登录方式</dt>
                  <dd className="mt-1 text-text-col-primary">账号 + 密码</dd>
                </div>
              </dl>
            </section>

            <div className="space-y-5">
              <div className="grid gap-3 md:grid-cols-3">
                <StatCard label="我的订单" value={String(orders.length)} detail="当前账号下的订单" />
                <StatCard label="售后记录" value={String(refunds.length)} detail="已提交的售后申请" />
                <StatCard label="处理中" value={String(activeRefunds)} detail="待审核或处理中" />
              </div>

              <section className="rounded border border-border-col bg-background-surface p-5">
                <div className="mb-4 flex items-center justify-between gap-4">
                  <div className="flex items-center gap-2 text-text-col-primary"><PackageSearch size={18} /><h2 className="font-semibold">最近订单</h2></div>
                  <Link href="/orders" className="text-sm text-accent hover:text-accent-light">查看全部</Link>
                </div>
                {latestOrder ? (
                  <div className="flex flex-col gap-4 rounded border border-border-col bg-background-base p-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-semibold text-text-col-primary">{latestOrder.product_name}</p>
                      <p className="mt-1 text-sm text-text-col-tertiary">订单号 {latestOrder.order_sn} · {latestOrder.status_label}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="font-semibold text-accent">¥{latestOrder.total_amount}</span>
                      <Link href={`/chat?order=${encodeURIComponent(latestOrder.order_sn)}`} className="rounded border border-accent/30 bg-accent/10 px-3 py-1.5 text-sm text-accent transition-colors hover:bg-accent/15">咨询此订单</Link>
                    </div>
                  </div>
                ) : <p className="rounded border border-border-col bg-background-base p-4 text-sm text-text-col-tertiary">当前账号暂无订单。</p>}
              </section>

              <section className="rounded border border-border-col bg-background-surface p-5">
                <div className="mb-4 flex items-center justify-between gap-4">
                  <div className="flex items-center gap-2 text-text-col-primary"><ReceiptText size={18} /><h2 className="font-semibold">售后进度</h2></div>
                  <Link href="/after-sales" className="text-sm text-accent hover:text-accent-light">查看全部</Link>
                </div>
                {latestRefund ? (
                  <div className="rounded border border-border-col bg-background-base p-4">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="font-semibold text-text-col-primary">{latestRefund.product_name}</p>
                        <p className="mt-1 text-sm text-text-col-tertiary">申请 #{latestRefund.id} · 订单号 {latestRefund.order_sn || "-"}</p>
                      </div>
                      <span className="w-fit rounded border border-warning/30 bg-warning/5 px-2.5 py-1 text-sm text-warning">{latestRefund.status_label}</span>
                    </div>
                  </div>
                ) : <p className="rounded border border-border-col bg-background-base p-4 text-sm text-text-col-tertiary">暂无售后申请记录。</p>}
              </section>

              <section className="grid gap-3 md:grid-cols-3">
                <Link href="/orders" className="rounded border border-border-col bg-background-surface p-4 text-sm text-text-col-secondary transition-colors hover:border-accent hover:text-accent"><UserRound className="mb-3" size={18} />查看我的订单</Link>
                <Link href="/after-sales" className="rounded border border-border-col bg-background-surface p-4 text-sm text-text-col-secondary transition-colors hover:border-accent hover:text-accent"><ReceiptText className="mb-3" size={18} />查看售后记录</Link>
                <Link href="/chat" className="rounded border border-border-col bg-background-surface p-4 text-sm text-text-col-secondary transition-colors hover:border-accent hover:text-accent"><MessageSquareText className="mb-3" size={18} />发起新的咨询</Link>
              </section>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
