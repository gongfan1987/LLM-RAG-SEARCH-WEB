"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/useAuthStore";
import { changePassword } from "@/lib/api/auth";

export default function SettingsPage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const initialized = useAuthStore((s) => s.initialized);
  const logout = useAuthStore((s) => s.logout);

  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );

  useEffect(() => {
    if (initialized && !user) {
      router.replace("/login");
    }
  }, [initialized, user, router]);

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault();
    if (!oldPassword || !newPassword) return;

    setSubmitting(true);
    setMessage(null);
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      setMessage({ type: "success", text: "密码已修改成功" });
      setOldPassword("");
      setNewPassword("");
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "修改密码失败",
      });
    } finally {
      setSubmitting(false);
    }
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  if (!user) return null;

  return (
    <div className="flex flex-1 justify-center bg-surface py-10">
      <div className="w-full max-w-md">
        <Link href="/chat" className="text-sm text-gray-500 hover:text-brand mb-4 inline-block">
          ← 返回对话
        </Link>

        <div className="rounded-2xl bg-white p-8 shadow-sm border border-border-subtle space-y-8">
          <div>
            <h2 className="text-sm font-medium text-gray-500 mb-2">当前账号</h2>
            <p className="text-base text-gray-900">{user.username}</p>
          </div>

          <form onSubmit={handleChangePassword} className="space-y-4">
            <h2 className="text-sm font-medium text-gray-500">修改密码</h2>
            <input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              placeholder="当前密码"
              autoComplete="current-password"
              className="w-full rounded-xl border border-border-subtle px-3.5 py-2.5 text-sm outline-none focus:border-brand transition-colors"
            />
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="新密码"
              autoComplete="new-password"
              className="w-full rounded-xl border border-border-subtle px-3.5 py-2.5 text-sm outline-none focus:border-brand transition-colors"
            />

            {message && (
              <p className={`text-sm ${message.type === "success" ? "text-green-600" : "text-red-500"}`}>
                {message.text}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-xl bg-brand text-brand-foreground py-2.5 text-sm font-medium hover:bg-brand/90 transition-colors disabled:opacity-50"
            >
              {submitting ? "提交中..." : "确认修改"}
            </button>
          </form>

          <div className="pt-4 border-t border-border-subtle">
            <button
              type="button"
              onClick={handleLogout}
              className="w-full rounded-xl border border-red-200 text-red-500 py-2.5 text-sm font-medium hover:bg-red-50 transition-colors"
            >
              退出登录
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
