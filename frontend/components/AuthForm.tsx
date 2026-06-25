"use client";

import { useState, type FormEvent } from "react";

interface AuthFormProps {
  mode: "login" | "register";
  loading: boolean;
  error: string | null;
  onSubmit: (username: string, password: string) => void;
}

/** 登录/注册共用表单：账号密码输入与提交，不承担网络请求逻辑 */
export function AuthForm({ mode, loading, error, onSubmit }: AuthFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    onSubmit(username.trim(), password);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm text-gray-600 mb-1.5">账号</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="请输入账号"
          autoComplete="username"
          className="w-full rounded-xl border border-border-subtle px-3.5 py-2.5 text-sm outline-none focus:border-brand transition-colors"
        />
      </div>
      <div>
        <label className="block text-sm text-gray-600 mb-1.5">密码</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="请输入密码"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          className="w-full rounded-xl border border-border-subtle px-3.5 py-2.5 text-sm outline-none focus:border-brand transition-colors"
        />
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-xl bg-brand text-brand-foreground py-2.5 text-sm font-medium hover:bg-brand/90 transition-colors disabled:opacity-50"
      >
        {loading ? "处理中..." : mode === "login" ? "登录" : "注册"}
      </button>
    </form>
  );
}
