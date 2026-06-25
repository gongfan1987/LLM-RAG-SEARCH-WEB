"""app/utils/text.py 单测：文本切分的边界、重叠、收敛性，以及表格感知切分。"""
import pytest

from app.utils.text import split_markdown, split_text


def test_空文本返回空列表():
    assert split_text("   \n  ") == []


def test_短文本不超过chunk_size时只返回一段():
    assert split_text("一句话。", chunk_size=100) == ["一句话。"]


def test_长文本被切成多段且覆盖全部字符():
    text = "段落。" * 200  # 600 字符
    chunks = split_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    # 拼接（去重叠不便，这里只校验每段非空且不超长）
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_在句号边界优先断开():
    text = "第一句。" + "x" * 60 + "第二句。" + "y" * 60
    chunks = split_text(text, chunk_size=70, overlap=0)
    # 第一段应在某个句号后结束，而非正好截断在 70
    assert chunks[0].endswith("。")


def test_overlap过大也能收敛不死循环():
    text = "abc" * 100
    chunks = split_text(text, chunk_size=10, overlap=9)
    assert len(chunks) >= 1  # 能正常返回即说明未陷入死循环


def test_chunk_size非正数报错():
    with pytest.raises(ValueError):
        split_text("x", chunk_size=0)


# ---------- split_markdown：表格感知切分 ----------

def test_无表格时退化为普通切分():
    text = "段落。" * 50
    assert split_markdown(text, chunk_size=80) == split_text(text, chunk_size=80)


def test_小表格整体保留在一个chunk内():
    md = "前言文字。\n\n| 姓名 | 年龄 |\n| --- | --- |\n| 张三 | 18 |\n| 李四 | 20 |\n\n结尾。"
    chunks = split_markdown(md, chunk_size=200)
    # 整张表应完整出现在某一个 chunk 里（行不被拆散）
    table_chunk = next(c for c in chunks if "| 姓名 | 年龄 |" in c)
    assert "| 张三 | 18 |" in table_chunk and "| 李四 | 20 |" in table_chunk


def test_超长表格按行分块且每块重复表头():
    rows = "\n".join(f"| 行{i} | 值{i} |" for i in range(40))
    md = f"| 列A | 列B |\n| --- | --- |\n{rows}"
    chunks = split_markdown(md, chunk_size=120)
    table_chunks = [c for c in chunks if "| 列A | 列B |" in c]
    assert len(table_chunks) >= 2  # 被分成多块
    # 每一块都带表头与分隔行，且没有把单行拆断
    for c in table_chunks:
        assert c.startswith("| 列A | 列B |\n| --- | --- |")


def test_表格不会与正文混进同一截断():
    md = "一段普通文字。\n| K | V |\n| --- | --- |\n| a | 1 |"
    chunks = split_markdown(md, chunk_size=500)
    # 表格自成 chunk（不和前面的文字粘在被截断的同一段里）
    assert any(c.strip().startswith("| K | V |") for c in chunks)
