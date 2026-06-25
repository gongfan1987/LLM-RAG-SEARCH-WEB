"use client";

import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";

interface GuestLimitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** 游客试用次数用尽时弹出，引导登录/注册 */
export function GuestLimitDialog({ open, onOpenChange }: GuestLimitDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[90vw] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-6 shadow-lg">
          <Dialog.Title className="text-lg font-semibold text-gray-900">
            免费试用次数已用完
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-gray-500">
            登录后可继续对话，并保存你的历史会话记录。
          </Dialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close className="rounded-xl px-4 py-2 text-sm text-gray-500 hover:bg-gray-100 transition-colors">
              稍后再说
            </Dialog.Close>
            <Link
              href="/login"
              className="rounded-xl bg-brand px-4 py-2 text-sm text-brand-foreground hover:bg-brand/90 transition-colors"
            >
              去登录
            </Link>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
