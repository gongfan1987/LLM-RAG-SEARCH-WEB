"""app/utils/rerank.py 单测：开关、排序、降级与边界，全程不触达真实 rerank 服务。

mock 说明：httpx.post 用替身替换——不发真实 HTTP 请求；get_settings 用伪 settings 控制开关。
"""
import app.utils.rerank as rr


def _settings(enabled=True, key="k", model="m"):
    return type(
        "S",
        (),
        {
            "rerank_configured": bool(enabled and key and model),
            "rerank_model": model,
            "rerank_base_url": "http://rerank.local",
            "effective_rerank_api_key": key,
            "rerank_timeout": 10.0,
        },
    )()


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_未启用时返回原顺序且不调用接口(monkeypatch):
    monkeypatch.setattr(rr, "get_settings", lambda: _settings(enabled=False))
    called = {"n": 0}
    monkeypatch.setattr(rr.httpx, "post", lambda *a, **k: called.update(n=called["n"] + 1))
    assert rr.rerank("q", ["a", "b", "c"], top_n=2) == [0, 1]
    assert called["n"] == 0


def test_重排成功时按接口结果重新排序(monkeypatch):
    monkeypatch.setattr(rr, "get_settings", lambda: _settings())
    payload = {"output": {"results": [{"index": 2}, {"index": 0}, {"index": 1}]}}
    monkeypatch.setattr(rr.httpx, "post", lambda *a, **k: FakeResp(payload))
    assert rr.rerank("q", ["a", "b", "c"], top_n=3) == [2, 0, 1]


def test_截断到top_n并过滤越界下标(monkeypatch):
    monkeypatch.setattr(rr, "get_settings", lambda: _settings())
    payload = {"output": {"results": [{"index": 1}, {"index": 9}, {"index": 0}]}}  # 9 越界
    monkeypatch.setattr(rr.httpx, "post", lambda *a, **k: FakeResp(payload))
    assert rr.rerank("q", ["a", "b"], top_n=5) == [1, 0]


def test_接口失败时降级为原顺序(monkeypatch):
    monkeypatch.setattr(rr, "get_settings", lambda: _settings())

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(rr.httpx, "post", boom)
    assert rr.rerank("q", ["a", "b", "c"], top_n=2) == [0, 1]


def test_空文档返回空(monkeypatch):
    monkeypatch.setattr(rr, "get_settings", lambda: _settings())
    assert rr.rerank("q", [], top_n=3) == []
