"""LLM 组件：封装 langchain 的全部细节（ChatOpenAI、工具调用循环、MCP 工具加载、文本向量化）。

对外公共接口（其余模块只应从这里引入，不要直连子模块）：
- stream_reply(messages) -> AsyncGenerator[(kind, text)]：流式对话 + 工具调用
- LlmCallError：调用失败的内部信号
- load_mcp_tools()：应用启动时加载一次 MCP 工具
- EmbeddingClient / EmbeddingError / get_embedding_client()：Qwen3-Embedding 文本向量化
"""
from app.llm.client import LlmCallError, stream_reply
from app.llm.embedding import EmbeddingClient, EmbeddingError, get_embedding_client
from app.llm.mcp import load_mcp_tools
from app.llm.tools import build_tool
from app.llm.vl import image_to_markdown

__all__ = [
    "LlmCallError",
    "stream_reply",
    "load_mcp_tools",
    "build_tool",
    "EmbeddingClient",
    "EmbeddingError",
    "get_embedding_client",
    "image_to_markdown",
]
