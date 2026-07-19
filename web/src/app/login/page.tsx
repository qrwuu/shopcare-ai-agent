"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { login } from "@/lib/api/auth";
import { toUserMessage } from "@/lib/api/errors";

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const normalizedAccount = account.trim();
    if (!/^\d{8}$/.test(normalizedAccount)) {
      setError("账号必须是 8 位数字。");
      return;
    }
    if (password.length < 6) {
      setError("密码至少需要 6 位。");
      return;
    }
    setLoading(true);
    try {
      const state = await login(normalizedAccount, password);
      if (state.user.is_admin) {
        router.replace("/admin");
        return;
      }
      router.push(searchParams.get("next") || "/");
    } catch (err) {
      setError(toUserMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-1 items-center justify-center bg-background-base px-6 py-12">
      <form onSubmit={submit} className="w-full max-w-sm rounded border border-border-col bg-background-surface p-6">
        <p className="text-xs font-mono text-accent">账号登录</p>
        <h1 className="mt-2 font-display text-3xl font-semibold text-text-col-primary">欢迎回来</h1>
        <p className="mt-2 text-sm leading-relaxed text-text-col-secondary">消费者使用 8 位账号进入订单与售后服务。内部员工登录后会进入审核工作台。</p>

        <label className="mt-6 block text-sm text-text-col-secondary" htmlFor="account">账号</label>
        <input
          id="account"
          value={account}
          onChange={(event) => setAccount(event.target.value.replace(/\D/g, "").slice(0, 8))}
          className="mt-2 w-full rounded border border-border-col bg-background-raised px-3 py-2.5 text-sm text-text-col-primary outline-none transition-colors placeholder:text-text-col-tertiary focus:border-accent"
          placeholder="请输入 8 位账号"
          inputMode="numeric"
          maxLength={8}
          aria-invalid={Boolean(error && account.trim().length !== 8)}
          required
        />

        <label className="mt-4 block text-sm text-text-col-secondary" htmlFor="password">密码</label>
        <input
          id="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-2 w-full rounded border border-border-col bg-background-raised px-3 py-2.5 text-sm text-text-col-primary outline-none transition-colors placeholder:text-text-col-tertiary focus:border-accent"
          placeholder="请输入密码"
          type="password"
          minLength={6}
          required
        />

        {error && <p className="mt-4 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</p>}

        <button disabled={loading} className="mt-6 w-full rounded bg-accent px-4 py-2.5 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90 disabled:opacity-50">
          {loading ? "登录中..." : "登录"}
        </button>

        <p className="mt-5 text-center text-sm text-text-col-tertiary">
          还没有账号？ <Link href="/register" className="text-accent hover:text-accent-light">立即注册</Link>
        </p>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginContent />
    </Suspense>
  );
}
