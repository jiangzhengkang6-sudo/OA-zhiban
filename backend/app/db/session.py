"""
OA 智能体管理系统 - 数据库会话模块。

创建异步 SQLAlchemy 引擎与会话工厂，提供 FastAPI 依赖 get_db。异步连接串用于业务
ORM（asyncpg），同步连接串仅预留给 LangGraph 同步 Checkpointer（如有需要）。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import get_settings
from sqlalchemy import event
from sqlalchemy.orm import Session

_settings = get_settings()

# 异步引擎（业务 ORM 主用）
engine = create_async_engine(_settings.database_url, echo=False, pool_pre_ping=True)

class AuthorizedSyncSession(Session):
    pass


@event.listens_for(AuthorizedSyncSession, 'before_commit')
def _before_commit(session):
    from ..services.authorization_service import verify_before_commit_sync
    verify_before_commit_sync(session)


class AuthorizedSession(AsyncSession):
    sync_session_class = AuthorizedSyncSession


# 异步会话工厂
async_session_factory = async_sessionmaker(
    engine, class_=AuthorizedSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供请求级数据库会话。

    Yields:
        AsyncSession: 数据库会话，请求结束后自动关闭。
    """
    async with async_session_factory() as session:
        yield session
