import type { ChatSession, SessionGroupKey } from "@/types/session";

const GROUP_ORDER: SessionGroupKey[] = ["今天", "昨天", "7天内", "更早"];

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function resolveGroup(updatedAt: string): SessionGroupKey {
  const updated = new Date(updatedAt);
  const today = startOfDay(new Date());
  const target = startOfDay(updated);
  const diffDays = Math.round((today - target) / (1000 * 60 * 60 * 24));

  if (diffDays <= 0) return "今天";
  if (diffDays === 1) return "昨天";
  if (diffDays <= 7) return "7天内";
  return "更早";
}

/** 将会话列表按 今天/昨天/7天内/更早 分组，组内按更新时间倒序 */
export function groupSessionsByDate(
  sessions: ChatSession[]
): { key: SessionGroupKey; sessions: ChatSession[] }[] {
  const buckets = new Map<SessionGroupKey, ChatSession[]>();

  const sorted = [...sessions].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  );

  for (const session of sorted) {
    const key = resolveGroup(session.updated_at);
    const list = buckets.get(key) ?? [];
    list.push(session);
    buckets.set(key, list);
  }

  return GROUP_ORDER.filter((key) => buckets.has(key)).map((key) => ({
    key,
    sessions: buckets.get(key)!,
  }));
}
