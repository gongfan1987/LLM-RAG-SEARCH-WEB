"""测试夹具：提供基于 sqlite 内存库的 SQLAlchemy Session。

仅用于需要真实 DB 的仓储/服务单测；建表前导入全部 ORM 模型以注册到 Base.metadata。
注意：sqlite 不真正执行 SELECT ... FOR UPDATE 行锁，故并发锁语义需在真实
Postgres/MySQL 做集成验证；此处覆盖追加/去重/版本递增等可在单连接验证的逻辑。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base

# 导入模型以注册到 Base.metadata（建表需要）。
import app.models.user  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.research.state.models  # noqa: F401
# 待 Task 4 创建 memory.models 后取消注释
# import app.research.memory.models  # noqa: F401


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
