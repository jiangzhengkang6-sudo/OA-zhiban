"""Local identity authority, separate from business OA provider records."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin


def new_id() -> str:
    return str(uuid4())


class IdentityRow(TimestampMixin):
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default='local')


class OAUser(Base, IdentityRow):
    __tablename__ = 'oa_user'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'id', name='uq_oa_user_tenant_identity'),
        UniqueConstraint('tenant_id', 'normalized_username', name='uq_oa_user_tenant_username'),
        CheckConstraint("status IN ('active', 'disabled')", name='user_status'),
        CheckConstraint('failed_attempts >= 0 AND auth_version >= 1 AND authorization_version >= 1', name='user_versions'),
    )
    normalized_username: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='active', nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    authorization_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_pending: Mapped[bool] = mapped_column(default=False, nullable=False)


class OADepartment(Base, IdentityRow):
    __tablename__ = 'oa_department'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'id', name='uq_oa_department_tenant_identity'),
        UniqueConstraint('tenant_id', 'name', name='uq_oa_department_tenant_name'),
        ForeignKeyConstraint(['tenant_id', 'parent_id'], ['oa_department.tenant_id', 'oa_department.id']),
        CheckConstraint('parent_id IS NULL OR parent_id <> id', name='department_parent'),
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class OAPosition(Base, IdentityRow):
    __tablename__ = 'oa_position'
    __table_args__ = (UniqueConstraint('tenant_id', 'id', name='uq_oa_position_tenant_identity'),
                      UniqueConstraint('tenant_id', 'name', name='uq_oa_position_tenant_name'))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class OAMembership(Base, TimestampMixin):
    __tablename__ = 'oa_membership'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'user_id'], ['oa_user.tenant_id', 'oa_user.id'], name='fk_oa_membership_user'),
        ForeignKeyConstraint(['tenant_id', 'department_id'], ['oa_department.tenant_id', 'oa_department.id']),
        ForeignKeyConstraint(['tenant_id', 'position_id'], ['oa_position.tenant_id', 'oa_position.id']),
        ForeignKeyConstraint(['tenant_id', 'manager_id'], ['oa_user.tenant_id', 'oa_user.id'], name='fk_oa_membership_manager'),
        CheckConstraint('manager_id IS NULL OR manager_id <> user_id', name='membership_manager'),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    position_id: Mapped[str | None] = mapped_column(String(64))
    manager_id: Mapped[str | None] = mapped_column(String(64))


class OARole(Base, IdentityRow):
    __tablename__ = 'oa_role'
    __table_args__ = (UniqueConstraint('tenant_id', 'id', name='uq_oa_role_tenant_identity'),
                      UniqueConstraint('tenant_id', 'code', name='uq_oa_role_tenant_code'))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class OAPermission(Base):
    __tablename__ = 'oa_permission'
    __table_args__ = (
        UniqueConstraint('resource', 'action', 'scope'),
        CheckConstraint("scope IN ('self', 'department')", name='permission_scope'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)


class OAUserRole(Base):
    __tablename__ = 'oa_user_role'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'user_id'], ['oa_user.tenant_id', 'oa_user.id']),
        ForeignKeyConstraint(['tenant_id', 'role_id'], ['oa_role.tenant_id', 'oa_role.id']),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class OARolePermission(Base):
    __tablename__ = 'oa_role_permission'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'role_id'], ['oa_role.tenant_id', 'oa_role.id']),
        ForeignKeyConstraint(['permission_id'], ['oa_permission.id']),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    permission_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class OAAuthSession(Base, IdentityRow):
    __tablename__ = 'oa_auth_session'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'user_id'], ['oa_user.tenant_id', 'oa_user.id']),
        Index('ix_oa_auth_session_family_id', 'family_id'),
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(64), nullable=False)
    refresh_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAAuthThrottle(Base):
    __tablename__ = 'oa_auth_throttle'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint('attempts >= 0', name='throttle_attempts'),)
