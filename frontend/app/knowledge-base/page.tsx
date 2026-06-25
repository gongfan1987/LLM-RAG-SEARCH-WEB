"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/useAuthStore";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  commitChunks,
  deleteDocument,
  getDocumentChunks,
  listDocuments,
  previewDocument,
} from "@/lib/api/knowledgeBase";
import type { KbScope, KnowledgeDocument } from "@/types/knowledgeBase";

interface EditChunk {
  text: string;
  kind: string;
  image_url: string;
}

interface EditorState {
  docId: string;
  filename: string;
  scope: KbScope;
  chunks: EditChunk[];
  /** "import" = 预览新文档后确认导入；"edit" = 编辑已入库文档后覆盖 */
  mode: "import" | "edit";
}

/**
 * 知识库管理页（需登录）。流程：
 * 1. 选文件 + 范围 → 预览（解析+切分，不入库）→ 逐 chunk 查看/编辑 → 确认导入；
 * 2. 已入库文档可「查看切片」，编辑后覆盖重新入库；
 * 3. 删除自己上传的文档。
 */
export default function KnowledgeBasePage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const initialized = useAuthStore((s) => s.initialized);

  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState<KbScope>("personal");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<KnowledgeDocument | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (initialized && !user) router.replace("/login");
  }, [initialized, user, router]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setDocs(await listDocuments());
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "加载文档失败" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialized && user) refresh();
  }, [initialized, user, refresh]);

  async function handlePreview() {
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setMessage({ type: "error", text: "请先选择一个文件（.txt / .md / .pdf / .docx / .xlsx）" });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const preview = await previewDocument(file, scope);
      setEditor({
        docId: preview.doc_id,
        filename: preview.filename,
        scope: preview.scope,
        chunks: preview.chunks.map((c) => ({ text: c.text, kind: c.kind, image_url: c.image_url })),
        mode: "import",
      });
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "预览失败" });
    } finally {
      setBusy(false);
    }
  }

  async function handleViewChunks(doc: KnowledgeDocument) {
    setBusy(true);
    setMessage(null);
    try {
      const chunks = await getDocumentChunks(doc.doc_id);
      setEditor({
        docId: doc.doc_id,
        filename: doc.filename,
        scope: doc.scope,
        chunks: chunks.map((c) => ({ text: c.text, kind: c.kind, image_url: c.image_url })),
        mode: "edit",
      });
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "加载切片失败" });
    } finally {
      setBusy(false);
    }
  }

  async function handleCommit() {
    if (!editor) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await commitChunks({
        doc_id: editor.docId,
        filename: editor.filename,
        scope: editor.scope,
        chunks: editor.chunks.map((c) => ({ text: c.text, kind: c.kind, image_url: c.image_url })),
      });
      setMessage({
        type: "success",
        text: `已${editor.mode === "edit" ? "更新" : "导入"}「${result.filename}」，共 ${result.chunks} 个片段`,
      });
      setEditor(null);
      await refresh();
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "入库失败" });
    } finally {
      setBusy(false);
    }
  }

  function updateChunk(index: number, text: string) {
    setEditor((e) =>
      e ? { ...e, chunks: e.chunks.map((c, i) => (i === index ? { ...c, text } : c)) } : e
    );
  }

  function removeChunk(index: number) {
    setEditor((e) => (e ? { ...e, chunks: e.chunks.filter((_, i) => i !== index) } : e));
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) return;
    try {
      await deleteDocument(pendingDelete.doc_id);
      setMessage({ type: "success", text: `已删除「${pendingDelete.filename}」` });
      await refresh();
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "删除失败" });
    }
  }

  if (!user) return null;

  return (
    <div className="flex flex-1 justify-center bg-surface py-10">
      <div className="w-full max-w-2xl px-4">
        <Link href="/chat" className="text-sm text-gray-500 hover:text-brand mb-4 inline-block">
          ← 返回对话
        </Link>

        <div className="rounded-2xl bg-white p-8 shadow-sm border border-border-subtle space-y-8">
          {message && (
            <p className={`text-sm ${message.type === "success" ? "text-green-600" : "text-red-500"}`}>
              {message.text}
            </p>
          )}

          {editor ? (
            <ChunkEditor
              editor={editor}
              busy={busy}
              onChange={updateChunk}
              onRemove={removeChunk}
              onCommit={handleCommit}
              onCancel={() => setEditor(null)}
            />
          ) : (
            <>
              {/* 上传 + 预览 */}
              <section className="space-y-4">
                <h1 className="text-base font-semibold text-gray-900">知识库</h1>
                <p className="text-sm text-gray-500">
                  上传 .txt / .md / .pdf / .docx / .xlsx（含表格、图片）。先预览切片、可逐段编辑微调，再确认入库。
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".txt,.md,.pdf,.docx,.xlsx"
                    className="text-sm text-gray-600 file:mr-3 file:rounded-lg file:border-0 file:bg-surface file:px-3 file:py-2 file:text-sm file:text-gray-700 hover:file:bg-gray-100"
                  />
                  <select
                    value={scope}
                    onChange={(e) => setScope(e.target.value as KbScope)}
                    className="rounded-xl border border-border-subtle px-3 py-2 text-sm outline-none focus:border-brand transition-colors"
                  >
                    <option value="personal">仅自己可见</option>
                    <option value="global">全局共享</option>
                  </select>
                  <button
                    type="button"
                    onClick={handlePreview}
                    disabled={busy}
                    className="rounded-xl bg-brand text-brand-foreground px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors disabled:opacity-50"
                  >
                    {busy ? "处理中..." : "预览切片"}
                  </button>
                </div>
              </section>

              {/* 文档列表 */}
              <section className="space-y-2 pt-2 border-t border-border-subtle">
                <h2 className="text-sm font-medium text-gray-500 pt-4">已有文档</h2>
                {loading ? (
                  <p className="text-sm text-gray-400 py-4">加载中...</p>
                ) : docs.length === 0 ? (
                  <p className="text-sm text-gray-400 py-4">暂无文档，先上传一份吧。</p>
                ) : (
                  <ul className="divide-y divide-border-subtle">
                    {docs.map((doc) => (
                      <li key={doc.doc_id} className="flex items-center justify-between gap-3 py-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm text-gray-900">{doc.filename}</p>
                          <p className="mt-0.5 flex items-center gap-2 text-xs text-gray-400">
                            <ScopeBadge scope={doc.scope} />
                            <span>{doc.chunks} 个片段</span>
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => handleViewChunks(doc)}
                            disabled={busy}
                            className="rounded-lg px-2.5 py-1.5 text-xs text-gray-500 hover:bg-surface transition-colors disabled:opacity-50"
                          >
                            查看切片
                          </button>
                          {doc.owner_id === user.id && (
                            <button
                              type="button"
                              onClick={() => setPendingDelete(doc)}
                              className="rounded-lg px-2.5 py-1.5 text-xs text-red-500 hover:bg-red-50 transition-colors"
                            >
                              删除
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="删除文档"
        description={
          pendingDelete
            ? `确定删除「${pendingDelete.filename}」？该文档的所有片段将从知识库移除。`
            : undefined
        }
        onOpenChange={(open) => !open && setPendingDelete(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}

function ChunkEditor({
  editor,
  busy,
  onChange,
  onRemove,
  onCommit,
  onCancel,
}: {
  editor: EditorState;
  busy: boolean;
  onChange: (index: number, text: string) => void;
  onRemove: (index: number) => void;
  onCommit: () => void;
  onCancel: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-gray-900">
            {editor.mode === "edit" ? "编辑切片：" : "预览切片："}
            {editor.filename}
          </h1>
          <p className="mt-0.5 text-xs text-gray-400">
            共 {editor.chunks.length} 段 · 可逐段编辑或删除，确认后{editor.mode === "edit" ? "覆盖更新" : "入库"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-xl px-4 py-2 text-sm text-gray-500 hover:bg-surface transition-colors disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onCommit}
            disabled={busy || editor.chunks.length === 0}
            className="rounded-xl bg-brand text-brand-foreground px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {busy ? "入库中..." : editor.mode === "edit" ? "保存覆盖" : "确认导入"}
          </button>
        </div>
      </div>

      <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
        {editor.chunks.map((chunk, i) => (
          <div key={i} className="rounded-xl border border-border-subtle p-3">
            <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
              <span className="flex items-center gap-2">
                <span>#{i + 1}</span>
                {chunk.kind === "image" && (
                  <span className="rounded bg-brand/10 px-1.5 py-0.5 text-brand">图片</span>
                )}
                {chunk.image_url && (
                  <a
                    href={chunk.image_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-brand hover:underline"
                  >
                    查看图片
                  </a>
                )}
              </span>
              <button
                type="button"
                onClick={() => onRemove(i)}
                className="text-red-500 hover:underline"
              >
                删除该段
              </button>
            </div>
            <textarea
              value={chunk.text}
              onChange={(e) => onChange(i, e.target.value)}
              rows={Math.min(8, Math.max(2, chunk.text.split("\n").length))}
              className="w-full resize-y rounded-lg border border-border-subtle bg-surface px-3 py-2 text-[13px] leading-relaxed outline-none focus:border-brand transition-colors"
            />
          </div>
        ))}
        {editor.chunks.length === 0 && (
          <p className="py-4 text-sm text-gray-400">已无片段，取消或重新预览。</p>
        )}
      </div>
    </section>
  );
}

function ScopeBadge({ scope }: { scope: KbScope }) {
  const isGlobal = scope === "global";
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
        isGlobal ? "bg-brand/10 text-brand" : "bg-gray-100 text-gray-500"
      }`}
    >
      {isGlobal ? "全局" : "个人"}
    </span>
  );
}
