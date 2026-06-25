"""文档解析组件：按扩展名把上传文件拆成有序内容块（文本/表格/图片）。

对外接口：parse_document(filename, raw) -> list[Block]。各格式解析器内部 lazy import
其依赖库，缺库时抛 UnsupportedFormatError（不影响应用启动与其他格式）。
"""
import os

from app.services.document_parsing.base import (
    Block,
    ImageBlock,
    TextBlock,
    UnsupportedFormatError,
)

# 已知但暂不支持的老式二进制格式（纯 Python 难以可靠解析），给出明确指引。
_LEGACY_HINTS = {
    ".doc": ".doc（Word 97-2003）",
    ".xls": ".xls（Excel 97-2003）",
}

__all__ = [
    "parse_document",
    "Block",
    "TextBlock",
    "ImageBlock",
    "UnsupportedFormatError",
]


def parse_document(filename: str, raw: bytes, vl_extract=None) -> list[Block]:
    """按文件扩展名分派到对应解析器，返回内容块列表。

    vl_extract：可选的「图片→markdown」回调（多模态 VL）；仅 PDF 用于含表格页面，其余忽略。
    """
    ext = os.path.splitext(filename.lower())[1]

    if ext in (".txt", ".md", ".markdown"):
        from app.services.document_parsing.plain import parse_text

        return parse_text(raw)
    if ext == ".pdf":
        from app.services.document_parsing.pdf import parse_pdf

        return parse_pdf(raw, vl_extract=vl_extract)
    if ext == ".docx":
        from app.services.document_parsing.docx import parse_docx

        return parse_docx(raw)
    if ext == ".xlsx":
        from app.services.document_parsing.excel import parse_excel

        return parse_excel(raw)

    if ext in _LEGACY_HINTS:
        raise UnsupportedFormatError(
            f"暂不支持 {_LEGACY_HINTS[ext]}，请另存为 .docx / .xlsx 后再上传"
        )
    raise UnsupportedFormatError(
        f"不支持的文件类型: {ext or '未知'}（支持 .txt / .md / .pdf / .docx / .xlsx）"
    )
