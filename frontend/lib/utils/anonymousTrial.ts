/**
 * 游客试用相关的本地存储工具。
 * 游客无需登录即可体验对话，但限制试用次数，用尽后引导登录。
 */

const ANONYMOUS_ID_KEY = "chat_anonymous_id";
const TRIAL_COUNT_KEY = "chat_anonymous_trial_count";

export const GUEST_TRIAL_LIMIT = 5;

function generateId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `anon_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

/** 获取（必要时生成）当前浏览器的匿名标识，用于未登录用户的请求头 X-Anonymous-Id */
export function getAnonymousId(): string {
  if (typeof window === "undefined") return "";
  let id = window.localStorage.getItem(ANONYMOUS_ID_KEY);
  if (!id) {
    id = generateId();
    window.localStorage.setItem(ANONYMOUS_ID_KEY, id);
  }
  return id;
}

/** 获取游客已使用的试用次数 */
export function getGuestTrialCount(): number {
  if (typeof window === "undefined") return 0;
  const raw = window.localStorage.getItem(TRIAL_COUNT_KEY);
  return raw ? Number(raw) || 0 : 0;
}

/** 游客剩余可用次数 */
export function getGuestTrialRemaining(): number {
  return Math.max(0, GUEST_TRIAL_LIMIT - getGuestTrialCount());
}

/** 游客发起一次对话后调用，自增已使用次数 */
export function incrementGuestTrialCount(): number {
  const next = getGuestTrialCount() + 1;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TRIAL_COUNT_KEY, String(next));
  }
  return next;
}

export function hasGuestTrialRemaining(): boolean {
  return getGuestTrialRemaining() > 0;
}
