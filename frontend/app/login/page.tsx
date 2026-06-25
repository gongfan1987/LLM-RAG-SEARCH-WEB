"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import { useAuthStore } from "@/store/useAuthStore";

export default function LoginPage() {
  const router = useRouter();
  const loginWithPassword = useAuthStore((s) => s.loginWithPassword);
  const loading = useAuthStore((s) => s.loading);
  const error = useAuthStore((s) => s.error);

  async function handleSubmit(username: string, password: string) {
    const ok = await loginWithPassword(username, password);
    if (ok) router.push("/chat");
  }

  return (
    <div className="flex flex-1 items-center justify-center bg-surface">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm border border-border-subtle">
        <h1 className="text-xl font-semibold text-gray-900 mb-1">欢迎回来</h1>
        <p className="text-sm text-gray-400 mb-6">登录以继续你的对话</p>

        <AuthForm mode="login" loading={loading} error={error} onSubmit={handleSubmit} />

        <p className="mt-5 text-center text-sm text-gray-500">
          还没有账号？
          <Link href="/register" className="text-brand font-medium ml-1 hover:underline">
            立即注册
          </Link>
        </p>
      </div>
    </div>
  );
}
