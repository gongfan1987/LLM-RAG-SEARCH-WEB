"""文档解析的公共类型与工具。

解析层只负责把各种格式「拆」成有序的内容块（文本/表格→文本、图片→原始字节），
不做 embedding、不碰 OSS/OCR——这些 I/O 由上层 knowledge_base_service 编排。
"""
from dataclasses import dataclass


class UnsupportedFormatError(Exception):
    """不支持的文件格式（由 knowledge_base_service 转成对用户的报错）。"""


@dataclass
class TextBlock:
    """一段文本内容（普通段落，或已序列化为 markdown 的表格）。"""

    text: str


@dataclass
class ImageBlock:
    """文档中内嵌的一张图片，保留原始字节供上层上传 OSS / OCR。"""

    data: bytes
    ext: str  # 扩展名（不含点），如 png / jpeg


Block = TextBlock | ImageBlock


def table_to_markdown(rows: list[list[str]]) -> str:
    """把二维表格序列化为 markdown 表格文本；空表返回空串。

    供检索：表格转成文本后才能被 embedding。首行作表头，单元格内换行压成空格。
    """
    cleaned = [
        [(cell or "").strip().replace("\n", " ") for cell in row]
        for row in rows
        if any((cell or "").strip() for cell in row)
    ]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    header = cleaned[0] + [""] * (width - len(cleaned[0]))
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in cleaned[1:]:
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
    return "\n".join(lines)
