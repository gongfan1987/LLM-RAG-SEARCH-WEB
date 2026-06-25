"""langchain 工具子系统：本地工具定义、注册表、执行与消息转换。

本地工具（如 get_current_date）是对话能力的一部分，集中在 LLM 组件内；
其依赖的纯日期格式化 now_local_str() 仍放在 utils/time.py（无业务含义的工具函数）。
"""
import ast
import operator
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool, tool

from app.llm.oss_tools import build_oss_tools
from app.llm.web_search import build_web_search_tools
from app.utils.time import now_local_str

_ROLE_TO_MESSAGE = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


@tool
def get_current_date() -> str:
    """获取服务器当前的日期和时间（本地时区，格式 YYYY-MM-DD HH:MM:SS）。

    当用户询问"今天几号""现在几点""当前日期"等与实时时间相关的问题时调用，
    不要凭空猜测日期。
    """
    return now_local_str()


# 仅允许这些算术运算符参与 calculate，杜绝 eval 执行任意代码的风险。
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    """递归求值算术 AST，只允许数字与白名单运算符，遇到其它结点即报错。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("不支持的表达式")


@tool
def calculate(expression: str) -> str:
    """做精确的算术计算，避免模型心算出错。

    支持 + - * / // % ** 和括号，例如 "(1+2)*3"、"2 ** 10"。
    仅做纯数值计算，不支持变量、函数或其它代码。
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
    except Exception:
        return f"无法计算表达式: {expression}（仅支持 + - * / // % ** 和括号的算术）"
    # 整数结果去掉多余的 .0，更符合直觉
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


@tool
def convert_timezone(time: str, from_tz: str, to_tz: str) -> str:
    """把某个时间从一个时区换算到另一个时区。

    time 格式为 "YYYY-MM-DD HH:MM" 或 "YYYY-MM-DD HH:MM:SS"；
    from_tz / to_tz 用 IANA 时区名，如 "Asia/Shanghai"、"UTC"、"America/New_York"。
    适用于把比赛/航班/会议等时间换算成用户所在时区。相对时间（明天/今天）请先用
    get_current_date 取得当前日期再组合成具体时间。
    """
    try:
        src, dst = ZoneInfo(from_tz), ZoneInfo(to_tz)
    except Exception:
        return f"未知时区: {from_tz} 或 {to_tz}（请用 IANA 名称，如 Asia/Shanghai）"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(time, fmt)
            break
        except ValueError:
            continue
    else:
        return f"无法解析时间: {time}（格式应为 YYYY-MM-DD HH:MM[:SS]）"
    return dt.replace(tzinfo=src).astimezone(dst).strftime("%Y-%m-%d %H:%M:%S %Z")


_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@tool
def date_offset(days: int, base_date: str = "") -> str:
    """计算某个日期偏移若干天后的日期及星期几。

    base_date 留空表示以服务器今天为基准（格式 YYYY-MM-DD）；days 可正可负。
    例如 base_date 留空、days=1 得到明天；days=-1 得到昨天；base_date 给定、days=0 查它是星期几。
    需要相对今天的「明天/N 天后」时，base_date 留空即可，无需先查当前日期。
    """
    try:
        base = datetime.strptime(base_date, "%Y-%m-%d").date() if base_date else date.today()
    except ValueError:
        return f"无法解析日期: {base_date}（格式应为 YYYY-MM-DD）"
    target = base + timedelta(days=days)
    return f"{target.isoformat()} {_WEEKDAYS[target.weekday()]}"


@tool
def days_between(start_date: str, end_date: str) -> str:
    """计算两个日期相差的天数（end_date - start_date，可为负），日期格式 YYYY-MM-DD。

    适用于「距某日还有几天」「距今过去了多少天」这类问题。
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return "无法解析日期（格式应为 YYYY-MM-DD）"
    return str((end - start).days)


# 本地工具集合：名称 -> 工具对象，便于按 tool_call 名称回查执行。
# 含基础工具（日期、计算、时区换算、日期运算）+ 联网搜索工具 + OSS 文件工具（按各自配置启用）。
LOCAL_TOOLS = {
    get_current_date.name: get_current_date,
    calculate.name: calculate,
    convert_timezone.name: convert_timezone,
    date_offset.name: date_offset,
    days_between.name: days_between,
    **{t.name: t for t in build_web_search_tools()},
    **{t.name: t for t in build_oss_tools()},
}


def build_tool(name: str, description: str, func: Callable[..., str]) -> BaseTool:
    """把一个普通可调用对象包装成 langchain 工具。

    供上层（如 RAG 知识库检索）按请求构造带上下文的工具，而无需自己依赖 langchain——
    langchain 细节统一收敛在本组件内。func 需带类型注解以便推断参数 schema。
    """
    return StructuredTool.from_function(func=func, name=name, description=description)


def to_lc_messages(messages: list[dict]) -> list[BaseMessage]:
    """把内部 {"role", "content"} 字典转换为 langchain 的消息对象。"""
    return [_ROLE_TO_MESSAGE.get(m["role"], HumanMessage)(content=m["content"]) for m in messages]


async def run_tool(call: dict, registry: dict[str, object]) -> str:
    """执行单个工具调用，返回字符串结果（异常也转为文本回灌给模型，由模型决定如何措辞）。

    统一走 ainvoke：本地工具与 MCP 工具都支持，MCP 工具本身就是异步的（需经子进程/连接）。
    """
    fn = registry.get(call["name"])
    if fn is None:
        return f"未知工具: {call['name']}"
    try:
        return str(await fn.ainvoke(call["args"]))
    except Exception as exc:  # 工具内部异常不应中断整个对话
        return f"工具 {call['name']} 执行失败: {exc}"
