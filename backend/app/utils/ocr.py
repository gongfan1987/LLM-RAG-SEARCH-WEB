"""图片 OCR：封装 RapidOCR，把图片字节识别为文字。

设计：lazy import + 进程级缓存引擎（首次加载模型较慢）。OCR 属增强能力——
未安装 rapidocr-onnxruntime、模型加载失败或识别异常时，统一降级为返回空串，
绝不让图片入库流程因此中断。
"""
import logging

logger = logging.getLogger(__name__)

_engine = None
_engine_loaded = False


def _get_engine():
    """惰性加载并缓存 OCR 引擎；不可用时返回 None。"""
    global _engine, _engine_loaded
    if _engine_loaded:
        return _engine
    _engine_loaded = True
    try:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    except Exception as exc:  # noqa: BLE001 未安装或初始化失败 → 降级
        logger.warning("OCR 引擎不可用，将跳过图片文字识别: %s", exc)
        _engine = None
    return _engine


def ocr_image(data: bytes) -> str:
    """识别图片中的文字；引擎不可用或识别失败时返回空串。"""
    engine = _get_engine()
    if engine is None:
        return ""
    try:
        result, _ = engine(data)
    except Exception as exc:  # noqa: BLE001 单张图片识别失败不影响整体
        logger.warning("OCR 识别失败，已跳过该图片: %s", exc)
        return ""
    if not result:
        return ""
    return "\n".join(line[1] for line in result if len(line) >= 2).strip()
