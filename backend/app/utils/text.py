"""纯辅助函数：文本切分。不包含任何业务规则（chunk 大小由调用方按场景传入）。"""
import re

# markdown 表格行：以 | 开头结尾（去空白后）。用于「表格不被切碎」的结构感知切分。
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
# markdown 表头分隔行，如 | --- | :--: |
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """把长文本切成若干带重叠的片段，尽量在自然边界（换行 / 句号）处断开。

    - chunk_size：每段最大字符数；overlap：相邻段重叠的字符数（用于保留上下文）。
    - 切分时在窗口后半段优先找换行或句号断开，避免把一句话拦腰截断。
    - 保证向前推进，不会因 overlap 过大而陷入死循环。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    text = text.strip()
    if not text:
        return []
    overlap = max(0, min(overlap, chunk_size - 1))

    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind("。"), window.rfind("."))
            # 只在断点落在窗口后半段时采用，避免片段过短。
            if cut >= chunk_size // 2:
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        # 下一段从 end-overlap 开始；若不前进则直接跳到 end，确保收敛。
        next_start = end - overlap
        start = next_start if next_start > start else end
    return chunks


def split_markdown(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """结构感知切分：普通文本按 split_text 切，**markdown 表格整体保留、绝不跨 chunk 截断**。

    复杂表格（PDF/Word/Excel 转成的 markdown 表）若被按字符数硬切，会让任一 chunk 都拿不到
    完整的表，检索/LLM 都读不懂。本函数把连续的表格行识别为整体：小表占一个 chunk；超长表按
    数据行分块，并在每块重复表头（含分隔行），保证每块都能读懂列含义。无表格时退化为 split_text。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    lines = text.split("\n")
    chunks: list[str] = []
    buffer: list[str] = []  # 累积的非表格文本

    def flush_text() -> None:
        block = "\n".join(buffer).strip()
        buffer.clear()
        if block:
            chunks.extend(split_text(block, chunk_size, overlap))

    i, n = 0, len(lines)
    while i < n:
        if _TABLE_ROW.match(lines[i]):
            j = i
            while j < n and _TABLE_ROW.match(lines[j]):
                j += 1
            flush_text()  # 表格前的文本先成块
            chunks.extend(_split_table(lines[i:j], chunk_size))
            i = j
        else:
            buffer.append(lines[i])
            i += 1
    flush_text()
    return chunks


def _split_table(table_lines: list[str], chunk_size: int) -> list[str]:
    """把一张 markdown 表切成若干 chunk：整表能放下则不拆；否则按数据行分块、每块重复表头。"""
    full = "\n".join(table_lines).strip()
    if not full:
        return []
    if len(full) <= chunk_size:
        return [full]
    # 表头：第一行；若第二行是分隔行（|---|），一并作为表头在每块重复。
    header = table_lines[:1]
    data_start = 1
    if len(table_lines) >= 2 and _TABLE_SEP.match(table_lines[1]):
        header = table_lines[:2]
        data_start = 2
    head_text = "\n".join(header)

    chunks: list[str] = []
    current: list[str] = []
    current_len = len(head_text)
    for row in table_lines[data_start:]:
        # 当前块非空且加上这行会超长 → 先收口（带表头），再起新块
        if current and current_len + len(row) + 1 > chunk_size:
            chunks.append(head_text + "\n" + "\n".join(current))
            current = []
            current_len = len(head_text)
        current.append(row)
        current_len += len(row) + 1
    if current:
        chunks.append(head_text + "\n" + "\n".join(current))
    return chunks or [full]
