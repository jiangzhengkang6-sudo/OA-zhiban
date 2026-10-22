"""
OA 智能体管理系统 - 数据库基类模块。

定义 SQLAlchemy 2.0 DeclarativeBase 与标准列类型别名，所有 ORM 模型统一继承 Base，
保证 metadata 单一来源，供 create_all 与 Alembic 迁移共享。
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约定，便于 Alembic 生成稳定的约束/索引名
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDMixin:
    """为模型提供 UUID 主键。"""

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )


class TimestampMixin:
    """为模型提供 created_at/updated_at 时间戳。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def uuid_default() -> UUID:
    """生成新的 UUID（作为列 default 的可调用对象）。

    Returns:
        UUID: 随机 UUID。
    """
    return uuid4()