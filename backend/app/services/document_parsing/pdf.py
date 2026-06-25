"""PDF 解析：正文 + 表格 → Markdown（表格保留为 markdown 表），图片单独提取走 OSS+OCR。

两种正文提取路径：
- 默认：pymupdf4llm 经典提取器（文本类，快；表格转 markdown，但合并表头等复杂结构会退化）。
- 可选 VL：注入 vl_extract 回调后，对**检测到表格的页面**渲染成图片交多模态模型转 markdown，
  更好还原复杂表格；其余页面仍走经典提取器。VL 调用失败时该页回退经典提取，不中断解析。

设计：网络型 VL 调用通过 vl_extract 回调**注入**，解析层本身不依赖具体模型，保持可单测。
"""
from collections.abc import Callable

from app.services.document_parsing.base import (
    Block,
    ImageBlock,
    TextBlock,
    UnsupportedFormatError,
)


def parse_pdf(raw: bytes, vl_extract: Callable[[bytes], str] | None = None) -> list[Block]:
    try:
        import fitz  # PyMuPDF
        import pymupdf4llm
    except ImportError as exc:
        raise UnsupportedFormatError("服务端未安装 PyMuPDF / pymupdf4llm，无法解析 .pdf") from exc

    # 经典提取器：避开新版 layout 模式自动触发的（与本机 rapidocr 不兼容会崩的）OCR。
    pymupdf4llm.use_layout(False)

    blocks: list[Block] = []
    seen_images: set[int] = set()
    document = fitz.open(stream=raw, filetype="pdf")
    try:
        markdown = _extract_markdown(document, pymupdf4llm, fitz, vl_extract)
        if markdown.strip():
            blocks.append(TextBlock(markdown.strip()))

        for page in document:
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_images:
                    continue
                seen_images.add(xref)
                try:
                    extracted = document.extract_image(xref)
                    blocks.append(ImageBlock(extracted["image"], extracted.get("ext", "png")))
                except Exception:  # noqa: BLE001 个别图片取不到则跳过
                    continue
    finally:
        document.close()

    return blocks


def _page_markdown(pymupdf4llm, document, page_number: int) -> str:
    """用经典提取器取单页 markdown；失败回退 get_text。"""
    try:
        return pymupdf4llm.to_markdown(document, pages=[page_number], show_progress=False)
    except Exception:  # noqa: BLE001
        return document[page_number].get_text()


def _extract_markdown(document, pymupdf4llm, fitz, vl_extract) -> str:
    """得到整篇 markdown。未注入 vl_extract 时整篇走经典提取；注入时含表页面用 VL、其余经典。"""
    if vl_extract is None:
        try:
            return pymupdf4llm.to_markdown(document, show_progress=False)
        except Exception:  # noqa: BLE001 整篇转换异常时退回纯文本
            return "\n".join(page.get_text() for page in document)

    parts: list[str] = []
    for page in document:
        has_table = False
        try:
            has_table = bool(page.find_tables().tables)
        except Exception:  # noqa: BLE001 表格探测失败按无表处理
            has_table = False
        page_md = ""
        if has_table:
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # ~2x 清晰度，利于识别表格
                page_md = vl_extract(pix.tobytes("png"))
            except Exception:  # noqa: BLE001 渲染/VL 失败则下面回退经典提取
                page_md = ""
        if not page_md.strip():
            page_md = _page_markdown(pymupdf4llm, document, page.number)
        parts.append(page_md)
    return "\n\n".join(parts)
