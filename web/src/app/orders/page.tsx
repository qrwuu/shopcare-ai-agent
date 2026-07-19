"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { listMyOrders } from "@/lib/api/customer";
import { getStoredAuth } from "@/lib/api/auth";
import { toUserMessage } from "@/lib/api/errors";
import type { CustomerOrder } from "@/types/customer";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

function OrderImage({ order }: { order: CustomerOrder }) {
  if (order.product_image) {
    return (
      <img
        src={order.product_image}
        alt={order.product_name}
        className="h-20 w-20 shrink-0 rounded border border-border-col bg-background-raised object-cover md:h-24 md:w-24"
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={(event) => {
          const target = event.currentTarget;
          target.style.display = "none";
          target.nextElementSibling?.classList.remove("hidden");
        }}
      />
    );
  }
  return null;
}

function OrderImageFallback({ order, hidden = false }: { order: CustomerOrder; hidden?: boolean }) {
  return (
    <div className={`${hidden ? "hidden" : ""} flex h-20 w-20 shrink-0 items-center justify-center rounded border border-border-col bg-background-raised text-2xl font-semibold text-accent md:h-24 md:w-24`}>
      {order.product_name.slice(0, 1)}
    </div>
  );
}

export default function OrdersPage() {
  const router = useRouter();
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const stored = getStoredAuth();
    if (!stored) {
      router.replace("/login?next=/orders");
      return;
    }
    if (stored.user.is_admin) {
      router.replace("/admin");
      return;
    }
    listMyOrders()
      .then(setOrders)
      .catch((err) => setError(toUserMessage(err)))
      .finally(() => setLoading(false));
  }, [router]);

  return (
    <div className="flex flex-1 overflow-y-auto bg-background-base px-6 py-8">
      <main className="mx-auto w-full max-w-5xl">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-mono text-accent">我的订单</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-text-col-primary">订单列表</h1>
          </div>
          <Link href="/chat" className="rounded bg-accent px-4 py-2 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90">开始售后咨询</Link>
        </div>

        {error && <div className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>}
        {loading ? <p className="text-sm text-text-col-tertiary">正在读取订单...</p> : null}

        <div className="grid gap-3">
          {orders.map((order) => (
            <section key={order.order_sn} className="rounded border border-border-col bg-background-surface p-4">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex min-w-0 items-center gap-4">
                  <div className="relative shrink-0">
                    <OrderImage order={order} />
                    <OrderImageFallback order={order} hidden={Boolean(order.product_image)} />
                  </div>
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold text-text-col-primary">{order.product_name}</h2>
                    <p className="mt-1 text-sm text-text-col-tertiary">订单号 {order.order_sn}</p>
                    <p className="mt-1 text-sm text-text-col-tertiary">下单时间 {formatTime(order.created_at)}</p>
                    <p className="mt-2 line-clamp-2 text-sm text-text-col-secondary">收货地址：{order.shipping_address}</p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <span className="rounded border border-border-col px-2.5 py-1 text-text-col-secondary">{order.status_label}</span>
                  <span className="font-semibold text-accent">¥{order.total_amount}</span>
                  <Link href={`/chat?order=${encodeURIComponent(order.order_sn)}`} className="rounded border border-accent/30 bg-accent/10 px-3 py-1.5 text-accent transition-colors hover:bg-accent/15">咨询此订单</Link>
                </div>
              </div>
            </section>
          ))}
          {!loading && orders.length === 0 && <p className="rounded border border-border-col bg-background-surface p-6 text-center text-sm text-text-col-tertiary">当前账号暂无订单。</p>}
        </div>
      </main>
    </div>
  );
}
