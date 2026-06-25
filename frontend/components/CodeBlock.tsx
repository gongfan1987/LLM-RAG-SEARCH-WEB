"use client";

import type { ComponentPropsWithoutRef } from "react";
import { CopyButton } from "@/components/CopyButton";

type PreProps = ComponentPropsWithoutRef<"pre">;

/** 提取 <pre><code>...</code></pre> 内的纯文本，用于复制按钮 */
function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (
    node &&
    typeof node === "object" &&
    "props" in node &&
    (node as { props?: { children?: React.ReactNode } }).props
  ) {
    return extractText((node as { props: { children?: React.ReactNode } }).props.children);
  }
  return "";
}

/** react-markdown 自定义渲染：代码块外层包裹一层带复制按钮的容器 */
export function CodeBlock(props: PreProps) {
  const text = extractText(props.children);

  return (
    <div className="relative group my-3">
      <pre
        {...props}
        className="rounded-xl border border-border-subtle bg-[#f7f8fa] p-4 overflow-x-auto text-sm font-mono"
      />
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <CopyButton text={text} />
      </div>
    </div>
  );
}
