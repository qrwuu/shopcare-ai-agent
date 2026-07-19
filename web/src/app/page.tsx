"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getStoredAuth } from "@/lib/api/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/api/storage";
import type { StoredAuthState } from "@/types/auth";

export default function LandingPage() {
  const [auth, setAuth] = useState<StoredAuthState | null>(null);

  useEffect(() => {
    const syncAuth = () => setAuth(getStoredAuth());
    syncAuth();
    window.addEventListener(AUTH_CHANGED_EVENT, syncAuth);
    window.addEventListener("storage", syncAuth);
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, syncAuth);
      window.removeEventListener("storage", syncAuth);
    };
  }, []);

  return (
    <div className="relative flex flex-1 overflow-hidden bg-background-base">
      <div className="absolute inset-0 pointer-events-none">
        <div
          className="absolute inset-0 opacity-[0.035]"
          style={{
            backgroundImage:
              "linear-gradient(#7DD3FC 1px,transparent 1px),linear-gradient(90deg,#7DD3FC 1px,transparent 1px)",
            backgroundSize: "56px 56px",
          }}
        />
        <div className="absolute inset-x-0 top-0 h-72 bg-[radial-gradient(ellipse_70%_55%_at_50%_0%,rgba(125,211,252,0.12),transparent)]" />
      </div>

      <main className="relative z-10 flex w-full items-center justify-center px-6 py-20">
        <section className="mx-auto w-full max-w-3xl text-center">
          <div>
            <p className="mb-5 text-sm font-mono font-semibold tracking-[0.24em] text-accent md:text-base">
              电商售后服务中台
            </p>
            <h1 className="font-display text-5xl font-bold leading-[1.08] text-text-col-primary md:text-7xl">
              店小服 ShopCare
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-2xl font-semibold leading-snug text-accent md:text-3xl">
              让售后处理更快、更稳、更可追踪
            </p>

            <div className="mt-12 flex flex-wrap justify-center gap-4">
              {auth ? (
                <Link
                  href={auth.user.is_admin ? "/admin" : "/chat"}
                  className="rounded bg-accent px-8 py-3 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90 active:opacity-75"
                >
                  {auth.user.is_admin ? "进入审核工作台" : "开始售后咨询"}
                </Link>
              ) : (
                <>
                  <Link
                    href="/login?next=/chat"
                    className="rounded bg-accent px-8 py-3 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90 active:opacity-75"
                  >
                    登录后咨询
                  </Link>
                  <Link
                    href="/register"
                    className="rounded border border-border-col px-8 py-3 text-sm font-medium text-text-col-secondary transition-colors hover:border-accent hover:text-accent"
                  >
                    注册账号
                  </Link>
                </>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
