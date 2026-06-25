"""app/utils/ocr.py 单测：引擎可用/不可用/识别异常下的行为，全部不触达真实模型。"""
import pytest

import app.utils.ocr as ocr


@pytest.fixture(autouse=True)
def reset_engine():
    ocr._engine = None
    ocr._engine_loaded = False
    yield
    ocr._engine = None
    ocr._engine_loaded = False


def test_引擎不可用时返回空串(monkeypatch):
    # 模拟未安装/初始化失败：_get_engine 返回 None
    monkeypatch.setattr(ocr, "_get_engine", lambda: None)
    assert ocr.ocr_image(b"imgbytes") == ""


def test_识别成功拼接各行文字(monkeypatch):
    class FakeEngine:
        def __call__(self, data):
            # rapidocr 返回 [[box, text, score], ...]
            return [[None, "第一行", 0.9], [None, "第二行", 0.8]], 0.01

    monkeypatch.setattr(ocr, "_get_engine", lambda: FakeEngine())
    assert ocr.ocr_image(b"x") == "第一行\n第二行"


def test_识别异常时降级为空串(monkeypatch):
    class BoomEngine:
        def __call__(self, data):
            raise RuntimeError("infer failed")

    monkeypatch.setattr(ocr, "_get_engine", lambda: BoomEngine())
    assert ocr.ocr_image(b"x") == ""


def test_无识别结果时返回空串(monkeypatch):
    monkeypatch.setattr(ocr, "_get_engine", lambda: (lambda data: ([], 0.0)))
    # 上面 lambda 作为 engine：engine(data) -> ([], 0.0)
    assert ocr.ocr_image(b"x") == ""
