"""可选端到端测试：真实 embedding + 真实 LLM + Milvus Lite，验证 RAG 工具链路。

⚠️ 默认跳过——它会发起真实外部调用（DashScope embedding、DeepSeek LLM），消耗 token。
开启方式：

    RUN_E2E=1 pytest tests/test_e2e_rag.py -s

前置条件：`.env` 配好 `EMBEDDING_*` 与 `LLM_API_KEY`；本地**无需**启动 Milvus 服务端
（用 Milvus Lite 本地文件，需 `pip install milvus-lite`，见 requirements-dev.txt）。

验证目标：
1. RAG 工具链路：上传「模型不可能预知的内部事实」→ 提问 → 断言模型主动触发
   search_knowledge_base 工具，且回答命中知识库事实（需 embedding + LLM）。
2. 切片预览/编辑链路：预览 → 改一段 → 提交入库 → 查回分片，验证编辑真实生效
   （仅需 embedding + Milvus Lite，无需 LLM）。
"""
import os

import pytest

from app.core.config import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_E2E"),
    reason="端到端测试默认跳过；设 RUN_E2E=1 且配好真实 EMBEDDING_*/LLM_API_KEY 后运行",
)

# 一条模型不可能预先知道的「内部事实」，只有检索知识库才能答对
_DOC = (
    "内部项目代号 Zephyr-9 的负责人是张伟，项目预算为 350 万元人民币，"
    "技术负责人是李娜，计划于 2027 年第二季度正式上线。"
).encode("utf-8")


async def test_模型按需触发知识库检索工具并据此回答(tmp_path, monkeypatch):
    settings = get_settings()
    if not (settings.embedding_configured and settings.llm_api_key):
        pytest.skip("缺少真实 EMBEDDING_*/LLM_API_KEY 配置")
    try:
        import milvus_lite  # noqa: F401
    except ImportError:
        pytest.skip("未安装 milvus-lite（pip install milvus-lite）")

    from app.llm import stream_reply
    from app.services import knowledge_base_service as kb
    from app.services import rag_service
    from app.utils.milvus import MilvusStore

    # 用 Milvus Lite 本地库重定向知识库存取；embedding / LLM 仍走真实服务。
    lite = MilvusStore(uri=str(tmp_path / "kb_e2e.db"), token="", collection="kb_e2e")
    monkeypatch.setattr(kb, "get_kb_milvus_client", lambda: lite)
    monkeypatch.setattr(rag_service, "get_kb_milvus_client", lambda: lite)

    # 包裹 retrieve_context，记录模型是否真的触发了知识库检索
    calls = {"n": 0}
    orig_retrieve = rag_service.retrieve_context

    def _wrapped(query, user_id, scope):
        calls["n"] += 1
        return orig_retrieve(query, user_id, scope)

    monkeypatch.setattr(rag_service, "retrieve_context", _wrapped)

    # 1. 导入文档
    result = kb.import_document("zephyr.txt", _DOC, "global", owner_id=1)
    assert result["chunks"] >= 1

    # 2. 构造检索工具
    tool = rag_service.make_kb_search_tool(user_id=1, scope="both")
    assert tool is not None and tool.name == "search_knowledge_base"

    # 3. 提问（答案只在知识库里），收集最终回复
    messages = [
        {
            "role": "system",
            "content": "你是一个有帮助的AI助手。当用户的问题可能与其上传的知识库资料有关时，"
            "请先调用 search_knowledge_base 工具检索，再据此回答。",
        },
        {"role": "user", "content": "内部项目 Zephyr-9 的负责人是谁？预算是多少？"},
    ]
    parts = []
    async for kind, text in stream_reply(messages, extra_tools=[tool]):
        if kind == "content":
            parts.append(text)
    answer = "".join(parts)

    assert calls["n"] > 0, "模型应主动触发 search_knowledge_base 工具"
    assert "张伟" in answer and "350" in answer, f"回答未命中知识库事实: {answer}"


def test_预览编辑提交后查看分片反映改动(tmp_path, monkeypatch):
    """预览 → 改一段 → 提交入库 → 查回分片，验证编辑在 Milvus 中真实生效（真实 embedding）。

    本用例不需要 LLM，只需 embedding + Milvus Lite。
    """
    settings = get_settings()
    if not settings.embedding_configured:
        pytest.skip("缺少真实 EMBEDDING_* 配置")
    try:
        import milvus_lite  # noqa: F401
    except ImportError:
        pytest.skip("未安装 milvus-lite（pip install milvus-lite）")

    from app.services import knowledge_base_service as kb
    from app.utils.milvus import MilvusStore

    lite = MilvusStore(uri=str(tmp_path / "kb_edit.db"), token="", collection="kb_edit")
    monkeypatch.setattr(kb, "get_kb_milvus_client", lambda: lite)

    # 长文确保切出多段，便于验证「只改其中一段」
    doc = ("苹果是红色的水果。" * 100).encode("utf-8")

    # 1. 预览（仅解析+切分，不写库）
    preview = kb.preview_document("fruit.txt", doc, "global")
    assert len(preview["chunks"]) >= 1

    # 2. 编辑第一段，注入哨兵文本
    chunks = [
        {"text": c["text"], "kind": c["kind"], "image_url": c["image_url"]}
        for c in preview["chunks"]
    ]
    sentinel = "【已编辑哨兵】葡萄是紫色的水果。"
    chunks[0]["text"] = sentinel

    # 3. 提交入库（真实 embedding + 写 Milvus）
    result = kb.commit_chunks(preview["doc_id"], "fruit.txt", "global", 1, chunks)
    assert result["chunks"] == len(chunks)

    # 4. 查回分片，确认编辑已生效
    stored = kb.get_document_chunks(preview["doc_id"], owner_id=1)
    assert len(stored) == len(chunks)
    assert any(sentinel in c["text"] for c in stored), "编辑后的内容未在入库分片中找到"
