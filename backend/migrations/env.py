"""Alembic supports CLI connections and transaction-scoped test connections."""
from alembic import context
from sqlalchemy import create_engine, pool
from app.core.config import get_settings
from app.db.base import Base
from app import models  # noqa: F401

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("基线需要检查已有表结构；请连接目标数据库执行迁移")
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    engine = create_engine(get_settings().database_sync_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
