from pydantic import BaseModel, Field


class DocumentImportResponse(BaseModel):
    doc_id: str
    filename: str
    chunks: int  # 切分并索引的片段数
    scope: str  # global | personal


class KnowledgeDocument(BaseModel):
    doc_id: str
    filename: str
    scope: str  # global | personal
    owner_id: int  # 上传者用户 id
    chunks: int  # 该文档的分片数


class ChunkPreview(BaseModel):
    index: int
    text: str
    kind: str = "text"  # text | image
    image_url: str = ""  # 图片块的 OSS 外链（如有）


class DocumentPreviewResponse(BaseModel):
    doc_id: str
    filename: str
    scope: str
    chunks: list[ChunkPreview]


class CommitChunk(BaseModel):
    text: str
    kind: str = "text"
    image_url: str = ""


class CommitChunksRequest(BaseModel):
    doc_id: str
    filename: str
    scope: str = Field(default="personal")  # global | personal
    chunks: list[CommitChunk]
