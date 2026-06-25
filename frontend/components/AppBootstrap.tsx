"use client";

import { useEffect } from "react";
import { useAuthStore } from "@/store/useAuthStore";

/**
 * 应用启动时恢复登录态（读取本地 token 并请求 /api/auth/me）。
 * 放在根布局内挂载一次，不承担任何渲染职责。
 */
export function AppBootstrap() {
  const restoreSession = useAuthStore((s) => s.restoreSession);

  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  return null;
}
