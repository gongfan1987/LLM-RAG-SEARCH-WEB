"""测试用伪实现：替代真实的 langchain 工具 / ChatOpenAI / MCP 客户端，
保证单测不触达真实 LLM、数据库或网络。"""


class FakeTool:
    """模拟一个 langchain 工具：有 name 与异步 ainvoke。

    result：ainvoke 的返回值；error：传入则 ainvoke 抛出该异常（覆盖工具失败场景）。
    """

    def __init__(self, name: str, result=None, error: Exception | None = None):
        self.name = name
        self._result = result
        self._error = error

    async def ainvoke(self, args):
        if self._error is not None:
            raise self._error
        return self._result


class FakeChunk:
    """模拟 ChatOpenAI.astream 产出的流式 chunk，只实现 stream_reply 用到的属性。

    - content：正文增量
    - additional_kwargs["reasoning_content"]：思维链增量（reasoning 非空时才放）
    - tool_calls：本轮模型请求的工具调用
    - __add__：支持 stream_reply 里 `gathered + chunk` 的累积
    """

    def __init__(self, content: str = "", reasoning: str | None = None, tool_calls=None):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}
        self.tool_calls = list(tool_calls or [])

    def __add__(self, other: "FakeChunk") -> "FakeChunk":
        merged = FakeChunk(content=self.content + other.content)
        merged.tool_calls = self.tool_calls + other.tool_calls
        return merged


class FakeLLM:
    """模拟 ChatOpenAI：bind_tools 返回自身；astream 按轮次产出预设 chunk。

    rounds：每个元素是一轮 astream 要产出的 chunk 列表（用于多轮工具调用场景）。
    raise_on_stream：传入则 astream 抛出该异常（覆盖底层调用失败场景）。
    """

    def __init__(self, rounds=None, raise_on_stream: Exception | None = None):
        self._rounds = [list(r) for r in (rounds or [])]
        self._raise = raise_on_stream
        self.astream_calls = 0
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def astream(self, messages):
        if self._raise is not None:
            raise self._raise
        chunks = self._rounds[self.astream_calls]
        self.astream_calls += 1
        for chunk in chunks:
            yield chunk
