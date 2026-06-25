"""对象存储（OSS）文件工具：让模型列出 / 获取访问链接，复用 app/utils/oss.py。

只读能力（列举 key、生成访问 URL），不下载对象内容、不写入，避免模型误删改存储。
仅在 OSS 已配置时注册（见 build_oss_tools），未配置则不暴露给模型——与 web_search、
MCP 等组件「未配置即降级」的风格一致。
"""
from langchain_core.tools import BaseTool, tool

from app.core.config import get_settings
from app.utils.oss import OssError, get_oss_client


@tool
def list_oss_files(prefix: str = "", limit: int = 20) -> str:
    """列出对象存储（OSS）中的文件，返回每个文件的 key 与访问链接。

    prefix 可按目录前缀筛选，如 "llm/2026/"；limit 限制返回数量。
    用于查看已存储的图片/视频/文件等资源。
    """
    try:
        client = get_oss_client()
        keys = client.list_objects(prefix=prefix, limit=limit)
    except OssError as exc:
        return f"OSS 操作失败: {exc}"
    if not keys:
        return f"未找到文件（prefix={prefix!r}）"
    return "\n".join(f"{key}\n{client.build_url(key)}" for key in keys)


@tool
def get_oss_file_url(key: str) -> str:
    """获取对象存储（OSS）中某个文件（key）的访问 URL。"""
    try:
        return get_oss_client().build_url(key)
    except OssError as exc:
        return f"OSS 操作失败: {exc}"


def build_oss_tools() -> list[BaseTool]:
    """OSS 文件工具列表：仅在 OSS 配置齐全时启用，否则返回空列表。"""
    if not get_settings().oss_configured:
        return []
    return [list_oss_files, get_oss_file_url]
