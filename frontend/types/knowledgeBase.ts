/** 文档可见范围：global 全局共享 / personal 仅本人可见 */
export type KbScope = "global" | "personal";

/** 对话时的知识库检索范围：none 关闭 / global 仅全局 / personal 仅个人 / both 全局+个人 */
export type KbRetrievalScope = "none" | "global" | "personal" | "both";

/** 知识库文档（后端按 doc_id 聚合分片后的视图） */
export interface KnowledgeDocument {
  doc_id: string;
  filename: string;
  scope: KbScope;
  owner_id: number; // 上传者用户 id；仅上传者本人可删除
  chunks: number; // 该文档的分片数
}

/** 文档导入成功的返回 */
export interface DocumentImportResponse {
  doc_id: string;
  filename: string;
  chunks: number;
  scope: KbScope;
}

/** 单个切片（预览/编辑用） */
export interface ChunkPreview {
  index: number;
  text: string;
  kind: string; // text | image
  image_url: string;
}

/** 预览文档（切分后、入库前）的返回 */
export interface DocumentPreview {
  doc_id: string;
  filename: string;
  scope: KbScope;
  chunks: ChunkPreview[];
}
