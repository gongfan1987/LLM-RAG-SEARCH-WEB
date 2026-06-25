"use client";

import Link from "next/link";

interface GuestBannerProps {
  remaining: number;
}

/** 游客模式下展示剩余试用次数，引导登录 */
export function GuestBanner({ remaining }: GuestBannerProps) {
  return (
    <div className="flex items-center justify-between gap-3 bg-brand/5 border border-brand/20 text-sm px-4 py-2 rounded-xl mx-4 mt-3">
      <span className="text-gray-600">
        游客模式：剩余 <span className="text-brand font-medium">{remaining}</span> 次免费对话
      </span>
      <Link
        href="/login"
        className="text-brand font-medium hover:underline shrink-0"
      >
        登录解锁完整体验
      </Link>
    </div>
  );
}
