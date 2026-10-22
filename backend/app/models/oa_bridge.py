"""Server-issued confirmation and committed business reconciliation records."""
from datetime import datetime
from sqlalchemy import DateTime,JSON,String,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key,tenant_fk


class OABridgeConfirmation(Base,IdentityRow):
    __tablename__='oa_bridge_confirmation'
    __table_args__=(tenant_key(__tablename__),tenant_fk('actor_id','oa_user'),
        tenant_fk('consumed_operation_id','oa_workflow_operation'))
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    thread_id: Mapped[str|None]=mapped_column(String(64))
    action: Mapped[str]=mapped_column(String(64),nullable=False)
    object_id: Mapped[str]=mapped_column(String(64),nullable=False)
    object_version: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    consumed_operation_id: Mapped[str|None]=mapped_column(String(64))


class OABridgeResult(Base,IdentityRow):
    __tablename__='oa_bridge_result'
    __table_args__=(tenant_key(__tablename__),tenant_fk('actor_id','oa_user'),tenant_fk('operation_id','oa_workflow_operation'),
        UniqueConstraint('tenant_id','actor_id','method','original_key'))
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    method: Mapped[str]=mapped_column(String(64),nullable=False)
    original_key: Mapped[str]=mapped_column(String(64),nullable=False)
    target_id: Mapped[str]=mapped_column(String(64),nullable=False)
    target_version: Mapped[str]=mapped_column(String(64),nullable=False)
    operation_id: Mapped[str]=mapped_column(String(64),nullable=False)
    result: Mapped[dict]=mapped_column(JSON,nullable=False)
