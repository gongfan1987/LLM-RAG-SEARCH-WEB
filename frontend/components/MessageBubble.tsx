import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { ChatMessage, ChatStep } from "@/types/message";
import { CodeBlock } from "@/components/CodeBlock";
import { CopyButton } from "@/components/CopyButton";

interface MessageBubbleProps {
  message: ChatMessage;
}

/** 工具名 → 中文可读标签；未知工具回退为原名 */
const TOOL_LABELS: Record<string, string> = {
  search_knowledge_base: "检索知识库",
  get_current_date: "获取当前时间",
  execute_sql: "执行数据库查询",
  get_schema_info: "查询数据库结构",
  get_table_sample: "查看数据样本",
};

function stepLabel(step: ChatStep): string {
  const base = TOOL_LABELS[step.tool] ?? step.tool;
  const detail = step.args?.query ?? step.args?.sql ?? step.args?.keyword;
  return typeof detail === "string" && detail ? `${base}：${detail}` : base;
}

/** 单条对话消息气泡：用户消息右对齐纯文本，AI 回复左对齐支持 Markdown + 代码高亮 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-2">
        <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-brand text-brand-foreground px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start px-4 py-2 group">
      <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-surface px-4 py-2.5 text-[15px] leading-relaxed shadow-sm">
        {message.reasoning && (
          <details
            className="mb-2 rounded-xl border border-border-subtle bg-background px-3 py-2"
            open
          >
            <summary className="cursor-pointer select-none text-[13px] text-foreground/55">
              💭 思考过程
            </summary>
            <div className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/70">
              {message.reasoning}
            </div>
          </details>
        )}
        {message.steps && message.steps.length > 0 && (
          <details
            className="mb-2 rounded-xl border border-border-subtle bg-background px-3 py-2"
            open
          >
            <summary className="cursor-pointer select-none text-[13px] text-foreground/55">
              🛠 执行过程
            </summary>
            <ul className="mt-2 space-y-1.5">
              {message.steps.map((step, i) => (
                <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed text-foreground/70">
                  <span className="mt-0.5 shrink-0">
                    {step.done ? (
                      <span className="text-green-600">✓</span>
                    ) : (
                      <span className="inline-block w-3 h-3 rounded-full border-2 border-brand/30 border-t-brand animate-spin" />
                    )}
                  </span>
                  <span className="break-all">{stepLabel(step)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className="prose prose-sm max-w-none prose-p:my-2 prose-headings:my-2">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{ pre: CodeBlock }}
          >
            {message.content}
          </ReactMarkdown>
          {message.streaming && (
            <span className="inline-block w-1.5 h-4 align-middle bg-brand/70 animate-pulse ml-0.5" />
          )}
        </div>
        {!message.streaming && message.content && (
          <div className="mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <CopyButton text={message.content} />
          </div>
        )}
      </div>
    </div>
  );
}
