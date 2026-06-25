"""Excel .xlsx 解析：每个工作表 → markdown 表格；内嵌图片 → 图片块。"""
from io import BytesIO

from app.services.document_parsing.base import (
    Block,
    ImageBlock,
    TextBlock,
    UnsupportedFormatError,
    table_to_markdown,
)


def parse_excel(raw: bytes) -> list[Block]:
    try:
        import openpyxl
    except ImportError as exc:
        raise UnsupportedFormatError("服务端未安装 openpyxl，无法解析 .xlsx") from exc

    workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True)
    blocks: list[Block] = []

    for sheet in workbook.worksheets:
        rows = [
            ["" if value is None else str(value) for value in row]
            for row in sheet.iter_rows(values_only=True)
        ]
        md = table_to_markdown(rows)
        if md:
            blocks.append(TextBlock(f"工作表「{sheet.title}」:\n{md}"))

        # openpyxl 把图片放在 ws._images（私有属性，按版本可能不存在）
        for image in getattr(sheet, "_images", []):
            try:
                data = image._data()  # type: ignore[attr-defined]
                ext = (getattr(image, "format", None) or "png").lower()
                blocks.append(ImageBlock(data, ext))
            except Exception:  # noqa: BLE001 取不到的图片跳过
                continue

    return blocks
