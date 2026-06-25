"""多模态视觉模型（VL）：把页面/图片转成 Markdown，主要用于还原 PDF 中的复杂表格。

默认对接 DashScope 的 Qwen-VL（OpenAI 兼容协议，复用 DashScope 凭证）。用 openai SDK 直连
（一次性视觉对话，无需流式）。属模型访问，归 app/llm。

降级：未配置（PDF_VL_ENABLED=false 或无 key）或调用失败时返回空串，由调用方回退到文本提取，
绝不让 VL 失败阻断文档解析。
"""
import base64
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_PROMPT = (
    "请把这张 PDF 页面图片的内容转换成 Markdown。"
    "其中的表格必须转成 markdown 表格，完整保留每个单元格的数据与表头"
    "（遇到合并表头时尽量拆解/对应到正确的列），不要遗漏数字；"
    "正文按阅读顺序输出。只输出 Markdown 内容本身，不要任何解释或代码围栏。"
)


def _strip_fences(text: str) -> str:
    """去掉模型可能加的 ```markdown ... ``` 围栏。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def image_to_markdown(image_bytes: bytes, ext: str = "png") -> str:
    """用 VL 模型把一张图片（通常是 PDF 页面渲染图）转成 Markdown；不可用/失败时返回空串。"""
    settings = get_settings()
    if not settings.vl_configured:
        return ""
    b64 = base64.b64encode(image_bytes).decode()
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.effective_vl_api_key,
            base_url=settings.vl_base_url,
            timeout=settings.vl_timeout,
            max_retries=1,
        )
        resp = client.chat.completions.create(
            model=settings.vl_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                    ],
                }
            ],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001 VL 是增强项，失败不应阻断解析
        logger.warning("VL 解析失败，跳过该页 VL: %s", exc)
        return ""
    return _strip_fences(content)
