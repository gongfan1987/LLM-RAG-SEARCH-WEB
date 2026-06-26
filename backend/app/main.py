"""FastAPI 应用入口：挂载中间件与路由，不在此处编写业务逻辑。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.base import Base, engine
from app.routers import auth, chat, knowledge_base, research, sessions

settings = get_settings()

app = FastAPI(title="AI Chat Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(knowledge_base.router)
app.include_router(research.router)


@app.on_event("startup")
def on_startup() -> None:
    # 开发环境便捷自动建表；生产环境建议使用 Alembic 迁移替代
    Base.metadata.create_all(bind=engine)


@app.on_event("startup")
async def load_external_tools() -> None:
    # MCP 工具只在启动时加载一次（MCP server 以子进程方式拉起，不能每次请求重复拉起）。
    # 未开启或加载失败时降级为无 MCP 工具，不阻断启动。
    from app.llm import load_mcp_tools

    await load_mcp_tools()


@app.on_event("startup")
async def warmup_rag_models() -> None:
    # 后台预热 embedding / rerank 远程服务，把首次冷启动延迟挪出用户请求路径。
    # 放后台跑（不 await 完成），不阻塞启动；best-effort，失败静默。
    import asyncio

    from app.services import rag_service

    asyncio.create_task(asyncio.to_thread(rag_service.warmup))


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
