"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LogOut, PackageSearch, ReceiptText, UserRound } from "lucide-react";
import { getStoredAuth, logout } from "@/lib/api/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/api/storage";
import type { StoredAuthState } from "@/types/auth";

const navLinks = [
  { href: "/chat", label: "售后咨询", exact: false },
];

export default function NavBar() {
  const pathname = usePathname();
  const [auth, setAuth] = useState<StoredAuthState | null>(null);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (!open) return;

    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [open]);

  const signOut = () => {
    logout();
    setOpen(false);
    window.location.assign("/");
  };

  if (pathname.startsWith("/admin")) return null;

  if (auth?.user?.is_admin) {
    return (
      <nav className="bg-background-surface border-b border-border-col px-6 py-3 flex items-center justify-between shrink-0">
        <Link href="/admin" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
          <div className="w-8 h-8 rounded bg-accent flex items-center justify-center text-accent-subtle font-bold text-xs font-mono shrink-0">审</div>
          <div>
            <p className="font-display font-semibold text-text-col-primary text-sm leading-tight">ShopCare 内部工作台</p>
            <p className="text-xs text-text-col-tertiary font-mono tracking-wide leading-tight">售后审核与协同处理</p>
          </div>
        </Link>

        <div className="flex items-center gap-2">
          <Link href="/admin" className="rounded border border-accent/30 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/15">审核工作台</Link>
          <button onClick={signOut} className="inline-flex items-center gap-2 rounded border border-border-col px-3 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-danger hover:text-danger"><LogOut size={14} /> 退出登录</button>
        </div>
      </nav>
    );
  }

  return (
    <nav className="bg-background-surface border-b border-border-col px-6 py-3 flex items-center justify-between shrink-0">
      <Link href="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
        <div className="w-8 h-8 rounded bg-accent flex items-center justify-center text-accent-subtle font-bold text-xs font-mono shrink-0">店</div>
        <div>
          <p className="font-display font-semibold text-text-col-primary text-sm leading-tight">店小服 ShopCare</p>
          <p className="text-xs text-text-col-tertiary font-mono tracking-wide leading-tight">售后服务助手</p>
        </div>
      </Link>

      <div className="flex items-center gap-2">
        <div className="hidden items-center gap-1 md:flex">
          {navLinks.map(({ href, label, exact }) => {
            const active = exact ? pathname === href : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`px-3 py-1.5 rounded text-xs font-mono font-medium transition-colors duration-150 border ${
                  active
                    ? "bg-accent/10 text-accent border-accent/30"
                    : "text-text-col-tertiary hover:text-text-col-secondary border-transparent"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </div>

        {!auth ? (
          <div className="flex items-center gap-2">
            <Link href="/login" className="rounded border border-border-col px-3 py-1.5 text-xs font-medium text-text-col-secondary transition-colors hover:border-accent hover:text-accent">登录</Link>
            <Link href="/register" className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-subtle transition-opacity hover:opacity-90">注册</Link>
          </div>
        ) : (
          <div ref={menuRef} className="relative">
            <button onClick={() => setOpen((value) => !value)} className="flex items-center gap-2 rounded border border-border-col bg-background-raised px-2.5 py-1.5 text-xs text-text-col-secondary transition-colors hover:border-accent hover:text-accent">
              <span className="flex h-6 w-6 items-center justify-center rounded bg-accent text-[11px] font-bold text-accent-subtle">{((auth.user?.full_name || auth.user?.username || "我")).slice(0, 1)}</span>
              <span className="max-w-24 truncate">{auth.user?.full_name || auth.user?.username || "个人中心"}</span>
            </button>

            {open && (
              <div className="absolute right-0 top-10 z-30 w-48 overflow-hidden rounded border border-border-col bg-background-surface shadow-2xl shadow-black/30">
                <Link href="/orders" onClick={() => setOpen(false)} className="flex items-center gap-2 px-3 py-2 text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-accent"><PackageSearch size={15} /> 我的订单</Link>
                <Link href="/after-sales" onClick={() => setOpen(false)} className="flex items-center gap-2 px-3 py-2 text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-accent"><ReceiptText size={15} /> 售后记录</Link>
                <Link href="/profile" onClick={() => setOpen(false)} className="flex items-center gap-2 px-3 py-2 text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-accent"><UserRound size={15} /> 个人中心</Link>
                <button onClick={signOut} className="flex w-full items-center gap-2 border-t border-border-col px-3 py-2 text-left text-sm text-text-col-secondary transition-colors hover:bg-background-raised hover:text-danger"><LogOut size={15} /> 退出登录</button>
              </div>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}
