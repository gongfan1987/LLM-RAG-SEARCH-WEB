"""app/utils/oss.py 单测：上传、URL 生成、错误包装与配置校验。

mock 说明：
- 用 FakeBucket 替身注入 OssClient，不创建真实 oss2.Bucket、不连阿里云、不发网络请求。
- settings 用 monkeypatch 设置，不依赖真实 .env。
"""
import pytest

from app.core.config import Settings
from app.utils.oss import OssClient, OssError


class FakeBucket:
    """记录调用参数的伪 bucket；可设置 error 模拟上传失败。"""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.put_object_calls: list[tuple] = []
        self.put_file_calls: list[tuple] = []

    def put_object(self, key, data, headers=None):
        if self.error:
            raise self.error
        self.put_object_calls.append((key, data, headers))

    def put_object_from_file(self, key, file_path, headers=None):
        if self.error:
            raise self.error
        self.put_file_calls.append((key, file_path, headers))


def _client(bucket=None, endpoint="https://oss-cn-hangzhou.aliyuncs.com", public_base_url=""):
    return OssClient(
        access_key_id="k",
        access_key_secret="s",
        endpoint=endpoint,
        bucket="my-bucket",
        public_base_url=public_base_url,
        _bucket=bucket or FakeBucket(),
    )


def test_上传二进制数据透传key与content_type并返回访问url():
    bucket = FakeBucket()
    url = _client(bucket).upload_bytes("llm/pic.png", b"data", content_type="image/png")
    assert bucket.put_object_calls == [("llm/pic.png", b"data", {"Content-Type": "image/png"})]
    assert url == "https://my-bucket.oss-cn-hangzhou.aliyuncs.com/llm/pic.png"


def test_未指定content_type时不传headers():
    bucket = FakeBucket()
    _client(bucket).upload_bytes("a.bin", b"x")
    assert bucket.put_object_calls == [("a.bin", b"x", None)]


def test_上传本地文件调用put_object_from_file():
    bucket = FakeBucket()
    url = _client(bucket).upload_file("dir/v.mp4", "/tmp/v.mp4", content_type="video/mp4")
    assert bucket.put_file_calls == [("dir/v.mp4", "/tmp/v.mp4", {"Content-Type": "video/mp4"})]
    assert url.endswith("/dir/v.mp4")


def test_配置自定义域名时优先用其生成url():
    client = _client(public_base_url="https://cdn.example.com/")
    assert client.build_url("/a/b.png") == "https://cdn.example.com/a/b.png"


def test_endpoint未带协议时默认按https推导域名():
    client = _client(endpoint="oss-cn-beijing.aliyuncs.com")
    assert client.build_url("x.png") == "https://my-bucket.oss-cn-beijing.aliyuncs.com/x.png"


def test_上传失败时包装为OssError而非泄漏底层异常():
    bucket = FakeBucket(error=RuntimeError("network down"))
    with pytest.raises(OssError) as exc:
        _client(bucket).upload_bytes("k", b"x")
    assert "network down" in str(exc.value)


class _Obj:
    def __init__(self, key):
        self.key = key


def test_列出对象按limit截断返回key(monkeypatch):
    import app.utils.oss as oss_mod

    monkeypatch.setattr(
        oss_mod.oss2, "ObjectIterator", lambda bucket, prefix="": [_Obj("a"), _Obj("b"), _Obj("c")]
    )
    assert _client().list_objects(prefix="", limit=2) == ["a", "b"]


def test_列出对象失败时包装为OssError(monkeypatch):
    import app.utils.oss as oss_mod

    def boom(bucket, prefix=""):
        raise RuntimeError("list down")

    monkeypatch.setattr(oss_mod.oss2, "ObjectIterator", boom)
    with pytest.raises(OssError) as exc:
        _client().list_objects()
    assert "list down" in str(exc.value)


def test_未配置oss时from_settings抛出OssError():
    settings = Settings(oss_access_key_id="", oss_access_key_secret="", oss_endpoint="", oss_bucket="")
    assert settings.oss_configured is False
    with pytest.raises(OssError):
        OssClient.from_settings(settings)


def test_配置齐全时oss_configured为真():
    settings = Settings(
        oss_access_key_id="k",
        oss_access_key_secret="s",
        oss_endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        oss_bucket="b",
    )
    assert settings.oss_configured is True
