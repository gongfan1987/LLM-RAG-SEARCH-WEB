/**
 * JWT 存储工具。
 *
 * 安全权衡说明：理想方案是后端将 token 写入 httpOnly Cookie，避免 XSS 读取风险。
 * 但当前后端契约里登录/注册接口直接在响应体返回 token（而非 Set-Cookie），
 * 且前后端是分离部署，短期内用 localStorage 存储、每次请求手动带 Authorization
 * header 实现更快、改造成本更低。后续如后端支持 httpOnly Cookie 签发，
 * 可以只替换本文件的实现，不影响上层调用方。
 */

const TOKEN_KEY = "chat_auth_token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}
