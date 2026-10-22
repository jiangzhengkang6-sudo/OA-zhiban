"""
OA 智能体管理系统 - pytest 全局配置。

设置 backend 根目录到 sys.path，触发 app 包导入以应用 Windows 事件循环策略，
并提供会话级 LangGraph 运行期 fixture。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 将 backend 根目录加入 sys.path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import app  # noqa: E402,F401  # 触发事件循环策略设置

# Set BEFORE application modules are collected; never inherit the development .env.
# Explicit process overrides are still checked again by every database fixture.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://oa:oa@localhost:5433/oa_agent_test"))
os.environ.setdefault("DATABASE_SYNC_URL", os.environ.get("TEST_DATABASE_SYNC_URL", "postgresql+psycopg://oa:oa@localhost:5433/oa_agent_test"))
os.environ.setdefault("CHECKPOINTER_URL", os.environ.get("TEST_CHECKPOINTER_URL", "postgresql://oa:oa@localhost:5433/oa_agent_test"))
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_DIM", "1536")
os.environ.setdefault("OA_PROVIDER", "mock")
os.environ.setdefault("AUTH_PROVIDER", "mock")
os.environ.setdefault("SMTP_ENABLED", "false")
os.environ.setdefault("WECOM_ENABLED", "false")
_mock_directory = tempfile.TemporaryDirectory(prefix="oa-agent-tests-")
os.environ["MOCK_STATE_FILE"] = str(Path(_mock_directory.name) / "mock_state.json")
os.environ["ATTACHMENT_STORAGE_DIR"] = str(Path(_mock_directory.name) / "attachments")
os.environ["CLAMD_HOST"] = ""


@pytest.fixture(scope="session")
def safe_database():
    from app.core.config import get_settings
    from app.db.safety import validate_test_targets

    settings = get_settings()
    validate_test_targets(
        settings.environment, settings.allow_test_database_reset,
        settings.database_url, settings.database_sync_url, settings.checkpointer_url,
    )
    return settings


@pytest.fixture(scope="session")
async def graph_ready(safe_database):
    """初始化数据库结构与 LangGraph 运行期（会话级单例）。

    Yield:
        无：仅提供初始化与清理副作用。
    """
    from alembic import command
    from app.db.migrations import migration_config
    import asyncio
    from app.db.session import engine
    from app.graph.graph_service import runtime
    from app import models  # noqa: F401

    await asyncio.to_thread(command.upgrade, migration_config(), "head")
    await runtime.initialize()
    yield
    await runtime.close()
    await engine.dispose()
