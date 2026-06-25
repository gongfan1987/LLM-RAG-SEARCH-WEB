from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: int | None = Field(
        default=None, description="登录用户可指定已有会话；为空则创建新会话。游客模式忽略该字段。"
    )
    kb_scope: str = Field(
        default="both",
        description="知识库检索范围：none 关闭 / global 仅全局 / personal 仅个人 / both 全局+个人（默认）。",
    )
