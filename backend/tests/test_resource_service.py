"""app/services/resource_service.py 单测：内联 base64 资源转存 OSS、替换为外链。

mock 说明：
- get_oss_client 用 FakeOss 替换——不创建真实 OSS 客户端、不发网络请求，并记录上传调用。
- get_settings 用伪 settings 替换——精确控制 oss_configured 开关，不依赖真实 .env。
"""
import base64

import pytest

import app.services.resource_service as rs
from app.utils.oss import OssError

PNG = base64.b64encode(b"\x89PNGfakebytes").decode()


class FakeOss:
    """记录 upload_bytes 调用并返回确定 URL 的伪 OSS 客户端；可设置上传失败。"""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def upload_bytes(self, key, data, content_type=None):
        if self.fail:
            raise OssError("upload failed")
        self.calls.append((key, data, content_type))
        return f"https://cdn.example.com/{key}"


@pytest.fixture
def patch_oss(monkeypatch):
    """提供工厂：开启 oss_configured，并用给定 FakeOss 替换 get_oss_client。"""

    def _apply(configured=True, fail=False):
        oss = FakeOss(fail=fail)
        monkeypatch.setattr(rs, "get_settings", lambda: type("S", (), {"oss_configured": configured})())
        monkeypatch.setattr(rs, "get_oss_client", lambda: oss)
        return oss

    return _apply


def test_内联图片被上传并替换为外链(patch_oss):
    oss = patch_oss()
    out = rs.store_inline_resources(f"![图](data:image/png;base64,{PNG})")
    assert oss.calls and oss.calls[0][2] == "image/png"
    assert oss.calls[0][0].endswith(".png")
    assert out == f"![图](https://cdn.example.com/{oss.calls[0][0]})"


def test_多个资源依据mime推导扩展名并全部替换(patch_oss):
    mp4 = base64.b64encode(b"fakemp4").decode()
    oss = patch_oss()
    out = rs.store_inline_resources(
        f"a data:image/jpeg;base64,{PNG} b data:video/mp4;base64,{mp4} c"
    )
    exts = [c[0].rsplit(".", 1)[1] for c in oss.calls]
    assert exts == ["jpg", "mp4"]
    assert "base64," not in out and out.count("https://cdn.example.com/") == 2


def test_未配置oss时原样返回且不调用上传(patch_oss):
    oss = patch_oss(configured=False)
    text = f"![图](data:image/png;base64,{PNG})"
    assert rs.store_inline_resources(text) == text
    assert oss.calls == []


def test_无内联资源时原样返回(patch_oss):
    oss = patch_oss()
    text = "普通回复，没有任何资源。"
    assert rs.store_inline_resources(text) == text
    assert oss.calls == []


def test_非法base64保留内联不抛出(patch_oss):
    patch_oss()
    text = "data:image/png;base64,@@@notbase64@@@"
    # 非法字符不被正则的 base64 字符集匹配，整体保持原样
    assert rs.store_inline_resources(text) == text


def test_上传失败时降级保留原始内联(patch_oss):
    patch_oss(fail=True)
    text = f"![图](data:image/png;base64,{PNG})"
    assert rs.store_inline_resources(text) == text
