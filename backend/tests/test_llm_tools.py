"""app/llm/tools.py 单测：本地工具、消息转换、工具执行。"""
import app.llm.tools as tools_mod
from app.llm.tools import (
    LOCAL_TOOLS,
    calculate,
    convert_timezone,
    date_offset,
    days_between,
    get_current_date,
    run_tool,
    to_lc_messages,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from tests.fakes import FakeTool


def test_获取当前日期工具返回格式化的本地时间(monkeypatch):
    # mock now_local_str：避免依赖真实时钟，断言工具直接透传其结果
    monkeypatch.setattr(tools_mod, "now_local_str", lambda: "2026-06-23 10:00:00")
    assert get_current_date.invoke({}) == "2026-06-23 10:00:00"


def test_获取当前日期工具已注册进本地工具集():
    assert LOCAL_TOOLS["get_current_date"] is get_current_date


def test_calculate按运算优先级计算():
    assert calculate.invoke({"expression": "2 + 3 * 4"}) == "14"


def test_calculate支持括号与幂和取模():
    assert calculate.invoke({"expression": "(1 + 2) ** 3 % 5"}) == "2"


def test_calculate拒绝非算术表达式返回提示():
    out = calculate.invoke({"expression": "__import__('os').system('ls')"})
    assert "无法计算" in out


def test_calculate工具已注册进本地工具集():
    assert LOCAL_TOOLS["calculate"] is calculate


def test_时区换算_上海时间转为utc():
    out = convert_timezone.invoke(
        {"time": "2026-06-26 12:00", "from_tz": "Asia/Shanghai", "to_tz": "UTC"}
    )
    assert out.startswith("2026-06-26 04:00:00")


def test_时区换算_未知时区返回提示():
    out = convert_timezone.invoke(
        {"time": "2026-06-26 12:00", "from_tz": "Mars/Base", "to_tz": "UTC"}
    )
    assert "未知时区" in out


def test_时区换算_时间格式错误返回提示():
    out = convert_timezone.invoke(
        {"time": "明天中午", "from_tz": "Asia/Shanghai", "to_tz": "UTC"}
    )
    assert "无法解析时间" in out


def test_时区换算工具已注册进本地工具集():
    assert LOCAL_TOOLS["convert_timezone"] is convert_timezone


def test_date_offset_指定基准日加一天为次日并带星期():
    out = date_offset.invoke({"days": 1, "base_date": "2026-06-25"})
    assert out.startswith("2026-06-26") and "星期" in out


def test_date_offset_负数往前推():
    out = date_offset.invoke({"days": -1, "base_date": "2026-06-25"})
    assert out.startswith("2026-06-24")


def test_date_offset_非法基准日返回提示():
    assert "无法解析" in date_offset.invoke({"days": 1, "base_date": "昨天"})


def test_days_between_计算相差天数():
    assert days_between.invoke({"start_date": "2026-06-25", "end_date": "2026-07-05"}) == "10"


def test_days_between_非法日期返回提示():
    assert "无法解析" in days_between.invoke({"start_date": "x", "end_date": "2026-07-05"})


def test_日期运算工具已注册进本地工具集():
    assert LOCAL_TOOLS["date_offset"] is date_offset
    assert LOCAL_TOOLS["days_between"] is days_between


def test_上下文消息按角色映射为对应的langchain消息():
    msgs = to_lc_messages(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "在的"},
        ]
    )
    assert [type(m) for m in msgs] == [SystemMessage, HumanMessage, AIMessage]
    assert [m.content for m in msgs] == ["你是助手", "你好", "在的"]


def test_未知角色的消息回退为用户消息():
    msgs = to_lc_messages([{"role": "function", "content": "x"}])
    assert isinstance(msgs[0], HumanMessage)


async def test_执行已知工具返回字符串结果():
    registry = {"echo": FakeTool("echo", result="数据库有 3 个用户")}
    result = await run_tool({"name": "echo", "args": {}, "id": "call_1"}, registry)
    assert result == "数据库有 3 个用户"


async def test_执行未知工具返回提示而不抛出():
    result = await run_tool({"name": "not_exist", "args": {}, "id": "call_1"}, {})
    assert "未知工具" in result and "not_exist" in result


async def test_工具内部异常被转为文本回灌而不中断对话():
    registry = {"boom": FakeTool("boom", error=ValueError("连接超时"))}
    result = await run_tool({"name": "boom", "args": {}, "id": "call_1"}, registry)
    assert "执行失败" in result and "连接超时" in result
