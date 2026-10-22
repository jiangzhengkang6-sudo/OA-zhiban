"""Formal tenant-scoped tickets, separate from legacy adapter records."""
from sqlalchemy import Boolean,CheckConstraint,Integer,JSON,String,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key,tenant_fk


class OATicketAssignmentRule(Base,IdentityRow):
    __tablename__='oa_ticket_assignment_rule'
    __table_args__=(tenant_key(__tablename__),tenant_fk('department_id','oa_department'),tenant_fk('assignee_id','oa_user'),
        UniqueConstraint('tenant_id','department_id','code','version'),CheckConstraint('version >= 1',name='ticket_rule_version'))
    department_id: Mapped[str]=mapped_column(String(64),nullable=False)
    code: Mapped[str]=mapped_column(String(64),nullable=False)
    version: Mapped[int]=mapped_column(Integer,nullable=False)
    category: Mapped[str]=mapped_column(String(64),nullable=False)
    impact: Mapped[str]=mapped_column(String(64),nullable=False)
    queue: Mapped[str]=mapped_column(String(128),nullable=False)
    assignee_id: Mapped[str|None]=mapped_column(String(64))
    priority: Mapped[int]=mapped_column(Integer,nullable=False)
    enabled: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)


class OATicket(Base,IdentityRow):
    __tablename__='oa_ticket'
    __table_args__=(tenant_key(__tablename__),tenant_fk('owner_id','oa_user'),tenant_fk('department_id','oa_department'),
        tenant_fk('assignee_id','oa_user'),tenant_fk('assignment_rule_id','oa_ticket_assignment_rule'),
        UniqueConstraint('tenant_id','business_no'),CheckConstraint('revision >= 1',name='ticket_revision'),
        CheckConstraint("state IN ('OPEN','IN_PROGRESS','RESOLVED','CLOSED')",name='formal_ticket_state'))
    business_no: Mapped[str]=mapped_column(String(64),nullable=False)
    owner_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    department_id: Mapped[str]=mapped_column(String(64),nullable=False)
    revision: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='OPEN')
    category: Mapped[str]=mapped_column(String(64),nullable=False)
    priority: Mapped[str]=mapped_column(String(16),nullable=False)
    impact: Mapped[str]=mapped_column(String(64),nullable=False)
    summary: Mapped[str]=mapped_column(String(2000),nullable=False)
    queue: Mapped[str|None]=mapped_column(String(128))
    assignee_id: Mapped[str|None]=mapped_column(String(64),index=True)
    assignment_rule_id: Mapped[str|None]=mapped_column(String(64))
    assignment_rule_version: Mapped[int|None]=mapped_column(Integer)
    assignment_error: Mapped[str|None]=mapped_column(String(500))
    merged_requests: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    resolution_note: Mapped[str|None]=mapped_column(String(2000))


class OATicketFeedback(Base,IdentityRow):
    __tablename__='oa_ticket_feedback'
    __table_args__=(tenant_key(__tablename__),tenant_fk('ticket_id','oa_ticket'),tenant_fk('actor_id','oa_user'),
        tenant_fk('operation_id','oa_workflow_operation'),UniqueConstraint('tenant_id','operation_id'))
    ticket_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    operation_id: Mapped[str]=mapped_column(String(64),nullable=False)
    resolved: Mapped[bool]=mapped_column(Boolean,nullable=False)
    comment: Mapped[str]=mapped_column(String(2000),nullable=False)
