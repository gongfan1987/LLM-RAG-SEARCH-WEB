import { getAnonymousId } from "@/lib/utils/anonymousTrial";
import { getAuthToken } from "@/lib/api/tokenStorage";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function buildHeaders(extra?: HeadersInit, jsonBody = true): Headers {
  const headers = new Headers(extra);
  // FormData（文件上传）需让浏览器自动带上 multipart 边界，不能手动设 Content-Type。
  if (jsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = getAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  } else {
    headers.set("X-Anonymous-Id", getAnonymousId());
  }
  return headers;
}

/** 兼容 FastAPI 的 `detail` 与历史 `message` 两种错误字段 */
function extractErrorMessage(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    if (typeof obj.detail === "string") return obj.detail;
    if (typeof obj.message === "string") return obj.message;
  }
  return `请求失败 (${status})`;
}

async function parseJsonSafe(response: Response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: buildHeaders(options.headers, !isFormData),
  });

  const data = await parseJsonSafe(response);

  if (!response.ok) {
    throw new ApiError(extractErrorMessage(data, response.status), response.status);
  }

  return data as T;
}

/** 暴露给 SSE 流式请求使用的 header 构造方法，避免重复鉴权逻辑 */
export function buildStreamHeaders(extra?: HeadersInit): Headers {
  return buildHeaders(extra);
}
