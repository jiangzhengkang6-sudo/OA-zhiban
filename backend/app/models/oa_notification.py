"""Private notification intents, channel receipts and immutable attempts."""
from datetime import datetime
from sqlalchemy import Boolean,CheckConstraint,DateTime,Index,Integer,JSON,String,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key,tenant_fk


class OAUserContact(Base,IdentityRow):
    __tablename__='oa_user_contact'
    __table_args__=(tenant_key(__tablename__),tenant_fk('user_id','oa_user'),UniqueConstraint('tenant_id','user_id',name='uq_oa_user_contact_key_0'))
    user_id: Mapped[str]=mapped_column(String(64),nullable=False)
    email: Mapped[str]=mapped_column(String(254),nullable=False)
    enabled: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    wecom_enabled: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default='false')


class OANotification(Base,IdentityRow):
    __tablename__='oa_notification'
    __table_args__=(tenant_key(__tablename__),tenant_fk('source_outbox_id','oa_workflow_outbox'),
        tenant_fk('recipient_id','oa_user'),tenant_fk('department_id','oa_department'),
        UniqueConstraint('tenant_id','source_outbox_id','recipient_id',name='uq_oa_notification_key_0'))
    source_outbox_id: Mapped[str]=mapped_column(String(64),nullable=False)
    recipient_id: Mapped[str]=mapped_column(String(64),nullable=False)
    department_id: Mapped[str | None]=mapped_column(String(64))
    source: Mapped[dict]=mapped_column(JSON,nullable=False)
    read_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))


class OANotificationDelivery(Base,IdentityRow):
    __tablename__='oa_notification_delivery'
    __table_args__=(tenant_key(__tablename__),tenant_fk('notification_id','oa_notification'),tenant_fk('wecom_batch_id','oa_wecom_batch'),
        UniqueConstraint('tenant_id','notification_id','channel',name='uq_oa_notification_delivery_key_0'),
        Index('ix_oa_notification_delivery_claim','channel','state','next_attempt_at'),
        CheckConstraint("channel IN ('inbox','smtp','wecom')",name='notification_channel'),
        CheckConstraint("state IN ('PENDING','PROCESSING','ACCEPTED','FAILED','UNKNOWN','CANCELLED')",name='notification_delivery_state'),
        CheckConstraint('attempt_count >= 0',name='notification_attempt_count'))
    notification_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    channel: Mapped[str]=mapped_column(String(16),nullable=False)
    state: Mapped[str]=mapped_column(String(16),nullable=False,default='PENDING')
    message_id: Mapped[str]=mapped_column(String(128),nullable=False)
    attempt_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    attempt_token: Mapped[str | None]=mapped_column(String(64))
    lease_until: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    last_code: Mapped[str | None]=mapped_column(String(64))
    destination_hash: Mapped[str | None]=mapped_column(String(64),index=True)
    wecom_batch_id: Mapped[str | None]=mapped_column(String(64),index=True)
    wecom_event_key: Mapped[str | None]=mapped_column(String(64),index=True)
    wecom_business_key: Mapped[str | None]=mapped_column(String(128),index=True)
    wecom_category: Mapped[str | None]=mapped_column(String(32))


class OAWecomBatch(Base,IdentityRow):
    __tablename__='oa_wecom_batch'
    __table_args__=(tenant_key(__tablename__),
        CheckConstraint("state IN ('PROCESSING','ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN','CANCELLED')",name='wecom_batch_state'))
    destination_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(16),nullable=False)
    lease_until: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    finished_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))


class OANotificationAttempt(Base,IdentityRow):
    __tablename__='oa_notification_attempt'
    __table_args__=(tenant_key(__tablename__),tenant_fk('delivery_id','oa_notification_delivery'),tenant_fk('wecom_batch_id','oa_wecom_batch'),
        UniqueConstraint('tenant_id','delivery_id','number',name='uq_oa_notification_attempt_key_0'),
        UniqueConstraint('tenant_id','token',name='uq_oa_notification_attempt_key_1'),
        CheckConstraint('number >= 1',name='notification_attempt_number'),
        CheckConstraint("state IN ('PROCESSING','ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN')",name='notification_attempt_state'))
    delivery_id: Mapped[str]=mapped_column(String(64),nullable=False)
    number: Mapped[int]=mapped_column(Integer,nullable=False)
    token: Mapped[str]=mapped_column(String(64),nullable=False)
    wecom_batch_id: Mapped[str | None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(16),nullable=False)
    finished_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
