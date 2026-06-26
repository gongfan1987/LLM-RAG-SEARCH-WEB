"""app/research/state/schema.py 单测：追加项子结构可构造、可 JSON 序列化、含来源标记。"""
from datetime import datetime

from app.research.state.schema import (
    Assumption, Chart, DataPoint, Draft, Fact, OutlineSection, Provenance, Review,
)


def _prov() -> Provenance:
    return Provenance(agent="retriever", source="kb:报告.pdf", created_at=datetime(2026, 6, 26))


def test_事实项带来源且可json序列化():
    fact = Fact(id="f1", content="GDP 增长 5%", provenance=_prov())
    dumped = fact.model_dump(mode="json")
    assert dumped["id"] == "f1"
    assert dumped["provenance"]["agent"] == "retriever"
    assert dumped["provenance"]["source"] == "kb:报告.pdf"


def test_假设默认状态为open():
    a = Assumption(id="a1", content="市场将扩张", provenance=_prov())
    assert a.status == "open"


def test_数据点单位可缺省():
    dp = DataPoint(id="d1", label="GDP", value="5%", unit=None, provenance=_prov())
    assert dp.unit is None


def test_评审反馈关联草稿并带结论():
    r = Review(id="r1", target_draft_id="dr1", comments=["论据不足"], verdict="revise", provenance=_prov())
    assert r.target_draft_id == "dr1"
    assert r.verdict == "revise"


def test_大纲章节与图表与草稿可构造():
    OutlineSection(id="o1", title="背景", points=["p1"], provenance=_prov())
    Chart(id="c1", title="趋势", chart_type="line", data_point_ids=["d1"], image_url=None, provenance=_prov())
    Draft(id="dr1", version=1, content="草稿正文", provenance=_prov())
