"""纯辅助函数：时间相关格式化。不包含任何业务规则。"""
from datetime import date, datetime, timezone


def today_utc_date() -> date:
    return datetime.now(timezone.utc).date()


def now_local_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """返回当前本地时间的格式化字符串，供需要展示当前日期/时间的场景使用。"""
    return datetime.now().strftime(fmt)
