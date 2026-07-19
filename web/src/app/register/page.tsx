"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { register } from "@/lib/api/auth";
import { toUserMessage } from "@/lib/api/errors";

export default function RegisterPage() {
  const router = useRouter();
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [account, setAccount] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const state = await register({ nickname: nickname.trim(), password });
      setAccount(state.user.username);
    } catch (err) {
      setError(toUserMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-1 items-center justify-center bg-background-base px-6 py-12">
      <div className="w-full max-w-sm rounded border border-border-col bg-background-surface p-6">
        {account ? (
          <div className="text-center">
            <p className="text-xs font-mono text-accent">注册成功</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-text-col-primary">请记住你的账号</h1>
            <div className="mt-6 rounded border border-accent/30 bg-accent/10 px-4 py-5 font-mono text-3xl font-semibold tracking-widest text-accent">
              {account}
            </div>
            <p className="mt-4 text-sm leading-relaxed text-text-col-secondary">以后请使用这个 8 位账号和密码登录。当前账号已自动登录。</p>
            <button onClick={() => router.push("/chat")} className="mt-6 w-full rounded bg-accent px-4 py-2.5 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90">
              开始售后咨询
            </button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <p className="text-xs font-mono text-accent">创建账号</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-text-col-primary">注册 ShopCare</h1>
            <p className="mt-2 text-sm leading-relaxed text-text-col-secondary">系统会自动生成唯一 8 位账号，昵称用于页面展示。</p>

            <label className="mt-6 block text-sm text-text-col-secondary" htmlFor="nickname">昵称</label>
            <input id="nickname" value={nickname} onChange={(event) => setNickname(event.target.value)} className="mt-2 w-full rounded border border-border-col bg-background-raised px-3 py-2.5 text-sm text-text-col-primary outline-none transition-colors placeholder:text-text-col-tertiary focus:border-accent" placeholder="例如：小林" required />

            <label className="mt-4 block text-sm text-text-col-secondary" htmlFor="password">密码</label>
            <input id="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded border border-border-col bg-background-raised px-3 py-2.5 text-sm text-text-col-primary outline-none transition-colors placeholder:text-text-col-tertiary focus:border-accent" placeholder="至少 6 位" type="password" minLength={6} required />

            {error && <p className="mt-4 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</p>}

            <button disabled={loading} className="mt-6 w-full rounded bg-accent px-4 py-2.5 text-sm font-semibold text-accent-subtle transition-opacity hover:opacity-90 disabled:opacity-50">
              {loading ? "注册中..." : "注册并登录"}
            </button>
            <p className="mt-5 text-center text-sm text-text-col-tertiary">
              已有账号？ <Link href="/login" className="text-accent hover:text-accent-light">去登录</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
