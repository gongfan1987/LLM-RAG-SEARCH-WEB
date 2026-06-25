"""app/llm/vl.py 单测：多模态图片→markdown，全程不触达真实 VL 服务。

mock 说明：openai.OpenAI 用替身替换——不发真实请求；get_settings 用伪 settings 控制开关。
"""
import openai

import app.llm.vl as vl


def _settings(enabled=True, key="k", model="qwen-vl-max"):
    return type(
        "S",
        (),
        {
            "vl_configured": bool(enabled and key and model),
            "effective_vl_api_key": key,
            "vl_model": model,
            "vl_base_url": "http://vl.local",
            "vl_timeout": 60.0,
        },
    )()


def _fake_openai(content):
    msg = type("M", (), {"content": content})()
    resp = type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    class Completions:
        def create(self, **kwargs):
            return resp

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self, **kwargs):
            self.chat = Chat()

    return Client


def test_未配置时返回空(monkeypatch):
    monkeypatch.setattr(vl, "get_settings", lambda: _settings(enabled=False))
    assert vl.image_to_markdown(b"imgbytes") == ""


def test_成功并去除代码围栏(monkeypatch):
    monkeypatch.setattr(vl, "get_settings", lambda: _settings())
    monkeypatch.setattr(openai, "OpenAI", _fake_openai("```markdown\n| a | b |\n| - | - |\n```"))
    out = vl.image_to_markdown(b"imgbytes")
    assert out == "| a | b |\n| - | - |"


def test_调用异常时降级为空(monkeypatch):
    monkeypatch.setattr(vl, "get_settings", lambda: _settings())

    class Boom:
        def __init__(self, **k):
            raise RuntimeError("vl service down")

    monkeypatch.setattr(openai, "OpenAI", Boom)
    assert vl.image_to_markdown(b"imgbytes") == ""
