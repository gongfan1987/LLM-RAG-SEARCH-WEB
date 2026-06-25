"""把外部 MCP server 暴露的工具接入 langchain 工具集。

职责边界：
- 仅负责 MCP 客户端的生命周期与工具加载，不含对话业务规则（那些在 chat_service）。
- MySQL 连接参数从 mysql_mcp_database_url 解析（留空回退 database_url），与主库解耦。

安全提示：开启后 LLM 可经 MCP 对数据库执行 SQL，务必为 MCP 配置只读账号 / 独立库，
不要直连存有密码哈希等敏感数据的主库。默认关闭（MYSQL_MCP_ENABLED=false）。
"""
import logging
import os
import shlex

from langchain_core.tools import BaseTool
from sqlalchemy.engine import make_url

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 启动时加载、运行期只读的 MCP 工具缓存。MCP server 经 stdio 子进程拉起，
# 在每次请求时再加载会反复拉起进程，因此只在应用启动时加载一次。
_mcp_tools: list[BaseTool] = []


def _mysql_env_from_database_url() -> dict[str, str]:
    """从 MCP 专用连接串解析出 MySQL MCP server 约定的连接环境变量。

    优先用 mysql_mcp_database_url（建议只读账号 / 独立库），留空则回退 database_url。
    """
    url = make_url(settings.effective_mcp_database_url)
    return {
        "MYSQL_HOST": url.host or "127.0.0.1",
        "MYSQL_PORT": str(url.port or 3306),
        "MYSQL_USER": url.username or "root",
        "MYSQL_PASSWORD": url.password or "",
        "MYSQL_DATABASE": url.database or "",
    }


def _build_connections() -> dict[str, dict]:
    """按各 MCP server 的开关拼装 connections（供 MultiServerMCPClient 一次性加载多个 server）。

    每个子进程都继承当前进程环境（保留 PATH 等，否则找不到解释器/命令），再叠加各自所需变量。
    未启用的 server 不出现在结果里；返回空字典表示没有任何 MCP server 需要加载。
    """
    connections: dict[str, dict] = {}
    if settings.mysql_mcp_enabled:
        connections["mysql"] = {
            "transport": "stdio",
            "command": settings.mysql_mcp_command,
            "args": shlex.split(settings.mysql_mcp_args),
            "env": {**os.environ, **_mysql_env_from_database_url()},
        }
    if settings.memory_mcp_enabled:
        memory_env = {**os.environ}
        if settings.memory_mcp_file_path:
            memory_env["MEMORY_FILE_PATH"] = settings.memory_mcp_file_path
        connections["memory"] = {
            "transport": "stdio",
            "command": settings.memory_mcp_command,
            "args": shlex.split(settings.memory_mcp_args),
            "env": memory_env,
        }
    return connections


async def load_mcp_tools() -> list[BaseTool]:
    """启动时调用一次：连接所有已启用的 MCP server（MySQL / Memory）并加载其工具，缓存到模块级。

    任何失败都降级为「无 MCP 工具」并记录日志，不阻断应用启动——
    MCP 属于增强能力，不应让它不可用导致整个对话服务起不来。
    """
    global _mcp_tools
    connections = _build_connections()
    if not connections:
        logger.info("无已启用的 MCP server（MYSQL_MCP_ENABLED / MEMORY_MCP_ENABLED 均关闭），跳过加载")
        return _mcp_tools

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("未安装 langchain-mcp-adapters，跳过 MCP 工具加载")
        return _mcp_tools

    try:
        client = MultiServerMCPClient(connections)
        _mcp_tools = await client.get_tools()
        logger.info(
            "已从 %s 加载 %d 个 MCP 工具: %s",
            list(connections),
            len(_mcp_tools),
            [t.name for t in _mcp_tools],
        )
    except Exception as exc:  # 连接/握手/进程拉起失败统一降级
        logger.warning("加载 MCP 工具失败，降级为无 MCP 工具: %s", exc)
        _mcp_tools = []
    return _mcp_tools


def get_mcp_tools() -> list[BaseTool]:
    """返回已加载的 MCP 工具列表（启动时由 load_mcp_tools 填充）。"""
    return _mcp_tools
