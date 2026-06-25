"""纯文本 / markdown 解析。"""
from app.services.document_parsing.base import Block, TextBlock, UnsupportedFormatError


def parse_text(raw: bytes) -> list[Block]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError("仅支持 UTF-8 编码的文本文件") from exc
    return [TextBlock(text)] if text.strip() else []
