"""app/llm/mcp.py 单测：连接参数解析、开关控制、加载成功与失败降级。

mock 说明：
- MultiServerMCPClient 用伪客户端替换——不真正拉起 MCP 子进程、不连数据库。
- settings 开关 / 连接串用 monkeypatch 设置——不依赖真实 .env。
- 每个用例前后重置模块级缓存 _mcp_tools，避免相互污染。
"""
import langchain_mcp_adapters.client as adapters_client
import pytest

import app.llm.mcp as mcp_mod
from app.llm.mcp import get_mcp_tools, load_mcp_tools
from tests.fakes import FakeTool


@pytest.fixture(autouse=True)
def reset_cache():
    mcp_mod._mcp_tools = []
    yield
    mcp_mod._mcp_tools = []


def test_从专用连接串解析出mysql环境变量(monkeypatch):
    monkeypatch.setattr(
        mcp_mod.settings, "mysql_mcp_database_url", "mysql+pymysql://u:p@dbhost:3307/mydb"
    )
    env = mcp_mod._mysql_env_from_database_url()
    assert env == {
        "MYSQL_HOST": "dbhost",
        "MYSQL_PORT": "3307",
        "MYSQL_USER": "u",
        "MYSQL_PASSWORD": "p",
        "MYSQL_DATABASE": "mydb",
    }


async def test_未启用时跳过加载并返回空列表(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", False)
    assert await load_mcp_tools() == []
    assert get_mcp_tools() == []


async def test_启用且加载成功时缓存并返回工具(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", True)
    fake_tools = [FakeTool("execute_sql"), FakeTool("get_schema_info")]

    class FakeClient:
        def __init__(self, connections):
            self.connections = connections

        async def get_tools(self):
            return fake_tools

    monkeypatch.setattr(adapters_client, "MultiServerMCPClient", FakeClient)
    result = await load_mcp_tools()
    assert [t.name for t in result] == ["execute_sql", "get_schema_info"]
    assert [t.name for t in get_mcp_tools()] == ["execute_sql", "get_schema_info"]


def _capturing_client(holder: dict, tools):
    """构造一个记录 connections 的伪 MultiServerMCPClient，并返回给定工具。"""

    class FakeClient:
        def __init__(self, connections):
            holder["connections"] = connections

        async def get_tools(self):
            return tools

    return FakeClient


async def test_启用memory时连接含memory条目并按配置拉起(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", False)
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_enabled", True)
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_command", "npx")
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_args", "-y @modelcontextprotocol/server-memory")
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_file_path", "")
    holder: dict = {}
    monkeypatch.setattr(
        adapters_client, "MultiServerMCPClient", _capturing_client(holder, [FakeTool("create_entities")])
    )
    result = await load_mcp_tools()
    assert [t.name for t in result] == ["create_entities"]
    conns = holder["connections"]
    assert "memory" in conns and "mysql" not in conns
    assert conns["memory"]["command"] == "npx"
    assert conns["memory"]["args"] == ["-y", "@modelcontextprotocol/server-memory"]


async def test_memory文件路径配置时注入环境变量(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", False)
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_enabled", True)
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_file_path", "/data/memory.json")
    holder: dict = {}
    monkeypatch.setattr(
        adapters_client, "MultiServerMCPClient", _capturing_client(holder, [FakeTool("x")])
    )
    await load_mcp_tools()
    assert holder["connections"]["memory"]["env"]["MEMORY_FILE_PATH"] == "/data/memory.json"


async def test_同时启用mysql与memory时两个server都在连接里(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", True)
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_enabled", True)
    holder: dict = {}
    monkeypatch.setattr(
        adapters_client, "MultiServerMCPClient", _capturing_client(holder, [FakeTool("x")])
    )
    await load_mcp_tools()
    assert set(holder["connections"]) == {"mysql", "memory"}


async def test_都未启用时跳过加载(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", False)
    monkeypatch.setattr(mcp_mod.settings, "memory_mcp_enabled", False)
    assert await load_mcp_tools() == []


async def test_启用但连接失败时降级为空且不抛出(monkeypatch):
    monkeypatch.setattr(mcp_mod.settings, "mysql_mcp_enabled", True)

    class FailingClient:
        def __init__(self, connections):
            pass

        async def get_tools(self):
            raise RuntimeError("connect failed")

    monkeypatch.setattr(adapters_client, "MultiServerMCPClient", FailingClient)
    assert await load_mcp_tools() == []
    assert get_mcp_tools() == []
