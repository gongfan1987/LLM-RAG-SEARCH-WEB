"""阿里云 OSS 工具类：封装 oss2 SDK，提供对象上传与访问 URL 生成。

只负责与 OSS 交互的技术细节，不含任何业务规则——上传什么、对象命名（key）策略
都由调用方决定。凭证与 bucket 配置全部来自环境变量（见 Settings.oss_*），
代码中不硬编码密钥。
"""
from functools import lru_cache

import oss2

from app.core.config import Settings, get_settings


class OssError(Exception):
    """OSS 操作失败的统一异常，避免把 oss2 的底层异常直接抛给调用方。"""


class OssClient:
    """阿里云 OSS 客户端封装：上传对象并返回可访问 URL。

    用法：
        client = get_oss_client()
        url = client.upload_bytes("llm/2026/pic.png", data, content_type="image/png")

    依赖：oss2（阿里云官方 SDK）。bucket 实例可通过 _bucket 注入，便于测试时替换。
    """

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        endpoint: str,
        bucket: str,
        public_base_url: str = "",
        *,
        _bucket: oss2.Bucket | None = None,
    ) -> None:
        self._bucket_name = bucket
        self._endpoint = endpoint
        self._public_base_url = public_base_url.rstrip("/")
        if _bucket is not None:
            self._bucket = _bucket
        else:
            auth = oss2.Auth(access_key_id, access_key_secret)
            self._bucket = oss2.Bucket(auth, endpoint, bucket)

    @classmethod
    def from_settings(cls, settings: Settings) -> "OssClient":
        if not settings.oss_configured:
            raise OssError("OSS 未配置：请设置 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_ENDPOINT / OSS_BUCKET")
        return cls(
            access_key_id=settings.oss_access_key_id,
            access_key_secret=settings.oss_access_key_secret,
            endpoint=settings.oss_endpoint,
            bucket=settings.oss_bucket,
            public_base_url=settings.oss_public_base_url,
        )

    def upload_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """上传二进制数据到指定 key，返回可访问 URL。"""
        headers = {"Content-Type": content_type} if content_type else None
        try:
            self._bucket.put_object(key, data, headers=headers)
        except Exception as exc:  # noqa: BLE001 统一包装 oss2 异常
            raise OssError(f"上传对象失败: {key}: {exc}") from exc
        return self.build_url(key)

    def upload_file(self, key: str, file_path: str, content_type: str | None = None) -> str:
        """上传本地文件到指定 key，返回可访问 URL。"""
        headers = {"Content-Type": content_type} if content_type else None
        try:
            self._bucket.put_object_from_file(key, file_path, headers=headers)
        except Exception as exc:  # noqa: BLE001 统一包装 oss2 异常
            raise OssError(f"上传文件失败: {key}: {exc}") from exc
        return self.build_url(key)

    def list_objects(self, prefix: str = "", limit: int = 50) -> list[str]:
        """列出指定前缀下的对象 key，最多返回 limit 个（只读，不下载对象内容）。"""
        try:
            keys: list[str] = []
            for obj in oss2.ObjectIterator(self._bucket, prefix=prefix):
                keys.append(obj.key)
                if len(keys) >= limit:
                    break
            return keys
        except Exception as exc:  # noqa: BLE001 统一包装 oss2 异常
            raise OssError(f"列举对象失败: prefix={prefix}: {exc}") from exc

    def build_url(self, key: str) -> str:
        """生成对象的访问 URL。配置了自定义域名/CDN 时优先使用，否则由 endpoint 推导。"""
        base = self._public_base_url or self._default_base_url()
        return f"{base}/{key.lstrip('/')}"

    def _default_base_url(self) -> str:
        """由 endpoint 与 bucket 推导默认访问域名：https://{bucket}.{host}。"""
        scheme, sep, host = self._endpoint.partition("://")
        if not sep:  # endpoint 未带协议时按 host 处理
            scheme, host = "https", self._endpoint
        return f"{scheme}://{self._bucket_name}.{host}"


@lru_cache
def get_oss_client() -> OssClient:
    """返回进程级单例 OSS 客户端；未配置 OSS 时抛出 OssError。"""
    return OssClient.from_settings(get_settings())
