"""app/llm/oss_tools.py 单测：OSS 文件工具（列出 / 取访问链接）与按配置注册。

mock 说明：get_oss_client 用伪客户端替换——不连阿里云、不发网络请求；
get_settings 用伪 settings 控制 OSS 是否已配置。
"""
import app.llm.oss_tools as ot
from app.utils.oss import OssError


class FakeOss:
    def __init__(self, keys=None, error: Exception | None = None):
        self._keys = keys or []
        self._error = error

    def list_objects(self, prefix="", limit=20):
        if self._error:
            raise self._error
        return [k for k in self._keys if k.startswith(prefix)][:limit]

    def build_url(self, key):
        return f"https://cdn/{key}"


def _settings(oss=True):
    return type("S", (), {"oss_configured": oss})()


def test_list_oss_files列出key与访问链接(monkeypatch):
    monkeypatch.setattr(ot, "get_oss_client", lambda: FakeOss(keys=["a.png", "b.png"]))
    out = ot.list_oss_files.invoke({"prefix": "", "limit": 10})
    assert "a.png" in out and "https://cdn/a.png" in out and "b.png" in out


def test_list_oss_files按prefix筛选(monkeypatch):
    monkeypatch.setattr(ot, "get_oss_client", lambda: FakeOss(keys=["llm/a.png", "other.txt"]))
    out = ot.list_oss_files.invoke({"prefix": "llm/", "limit": 10})
    assert "llm/a.png" in out and "other.txt" not in out


def test_list_oss_files无文件时返回提示(monkeypatch):
    monkeypatch.setattr(ot, "get_oss_client", lambda: FakeOss(keys=[]))
    assert "未找到文件" in ot.list_oss_files.invoke({"prefix": "x/", "limit": 10})


def test_list_oss_files失败时返回提示而不抛出(monkeypatch):
    monkeypatch.setattr(ot, "get_oss_client", lambda: FakeOss(error=OssError("boom")))
    assert "OSS 操作失败" in ot.list_oss_files.invoke({"prefix": "", "limit": 10})


def test_get_oss_file_url返回访问链接(monkeypatch):
    monkeypatch.setattr(ot, "get_oss_client", lambda: FakeOss())
    assert ot.get_oss_file_url.invoke({"key": "k.png"}) == "https://cdn/k.png"


def test_未配置oss时不注册工具(monkeypatch):
    monkeypatch.setattr(ot, "get_settings", lambda: _settings(oss=False))
    assert ot.build_oss_tools() == []


def test_配置oss后注册两个工具(monkeypatch):
    monkeypatch.setattr(ot, "get_settings", lambda: _settings(oss=True))
    names = [t.name for t in ot.build_oss_tools()]
    assert names == ["list_oss_files", "get_oss_file_url"]
