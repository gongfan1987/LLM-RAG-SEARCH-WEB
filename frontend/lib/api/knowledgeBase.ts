import { apiFetch } from "@/lib/api/client";
import type {
  ChunkPreview,
  DocumentImportResponse,
  DocumentPreview,
  KbScope,
  KnowledgeDocument,
} from "@/types/knowledgeBase";

/**
 * 上传并导入一份文档到知识库（需登录）。
 * 后端流程：切分 → embedding → 写入 Milvus。仅支持 UTF-8 文本/markdown。
 */
export function importDocument(
  file: File,
  scope: KbScope = "personal"
): Promise<DocumentImportResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("scope", scope);
  // 不手动设置 Content-Type：apiFetch 检测到 FormData 会交给浏览器带 multipart 边界。
  return apiFetch<DocumentImportResponse>("/api/knowledge-base/documents", {
    method: "POST",
    body: form,
  });
}

/** 预览：解析+切分文档，返回 chunk 列表（不写入 Milvus），供编辑后再提交 */
export function previewDocument(
  file: File,
  scope: KbScope = "personal"
): Promise<DocumentPreview> {
  const form = new FormData();
  form.append("file", file);
  form.append("scope", scope);
  return apiFetch<DocumentPreview>("/api/knowledge-base/documents/preview", {
    method: "POST",
    body: form,
  });
}

/** 提交（可能已编辑的）chunk 列表入库；用于确认导入或覆盖已入库文档 */
export function commitChunks(payload: {
  doc_id: string;
  filename: string;
  scope: KbScope;
  chunks: { text: string; kind?: string; image_url?: string }[];
}): Promise<DocumentImportResponse> {
  return apiFetch<DocumentImportResponse>("/api/knowledge-base/documents/commit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 查看某已入库文档的全部切片（供再次预览/编辑） */
export function getDocumentChunks(docId: string): Promise<ChunkPreview[]> {
  return apiFetch<ChunkPreview[]>(
    `/api/knowledge-base/documents/${encodeURIComponent(docId)}/chunks`
  );
}

/** 列出当前用户可见的文档：全部 global + 自己的 personal */
export function listDocuments(): Promise<KnowledgeDocument[]> {
  return apiFetch<KnowledgeDocument[]>("/api/knowledge-base/documents");
}

/** 删除文档（仅上传者本人可删；他人→403、不存在→404，均由 ApiError 抛出） */
export function deleteDocument(
  docId: string
): Promise<{ message: string; deleted_chunks: number }> {
  return apiFetch(`/api/knowledge-base/documents/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
}
