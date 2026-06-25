"""把 LLM 回复中内联的 base64 资源（图片/视频/文件）转存到阿里云 OSS，替换为外链。

为什么在这里做：deepseek-chat 等文本模型的回复是 markdown 文本，模型产出的媒体
只会以 data URI（`data:<mime>;base64,<data>`）内联在文本里。直接落库会让单条消息
膨胀到 MB 级，且每次加载历史都要重传。故在落库前把内联资源上传 OSS、替换为外链。

边界与降级：
- 未配置 OSS（`oss_configured=False`）或文本中无内联资源时，整体为 no-op，原样返回。
- 单个资源 base64 非法或上传失败时，保留其原始内联形式并继续处理其余资源，
  不抛出、不中断主流程（与 MCP 加载失败一致的降级策略）。
"""
import base64
import hashlib
import re
from datetime import datetime

from app.core.config import get_settings
from app.utils.oss import OssError, get_oss_client

# 匹配 markdown / HTML 中的 data URI：data:<mime>;base64,<base64 数据>
_DATA_URI_RE = re.compile(r"data:([\w.+-]+/[\w.+-]+);base64,([A-Za-z0-9+/]+={0,2})")

# 常见 MIME 到扩展名的映射；未命中时回退用 MIME 的子类型。
_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "video/mp4": "mp4",
    "audio/mpeg": "mp3",
    "application/pdf": "pdf",
}


def _ext_for(mime: str) -> str:
    return _MIME_EXT.get(mime) or mime.split("/")[-1]


def store_inline_resources(content: str) -> str:
    """把 content 中内联的 base64 资源转存 OSS，返回替换为外链后的文本。"""
    settings = get_settings()
    if not settings.oss_configured or "base64," not in content:
        return content

    client = get_oss_client()

    def _replace(match: re.Match) -> str:
        mime, b64 = match.group(1), match.group(2)
        try:
            data = base64.b64decode(b64, validate=True)
        except (ValueError, base64.binascii.Error):
            return match.group(0)  # 非法 base64，原样保留
        # 用内容哈希做 key，相同资源幂等映射到同一对象，避免重复占用空间。
        digest = hashlib.sha256(data).hexdigest()[:16]
        key = f"llm/{datetime.now():%Y%m%d}/{digest}.{_ext_for(mime)}"
        try:
            return client.upload_bytes(key, data, content_type=mime)
        except OssError:
            return match.group(0)  # 上传失败降级，保留内联

    return _DATA_URI_RE.sub(_replace, content)
