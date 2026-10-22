"""工单草稿的持久化与字段校验。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ticket_draft import TicketDraft
from ..schemas.ticket_draft import ALLOWED_DRAFT_FIELDS, ALLOWED_PRIORITIES


def validate_draft_fields(fields: dict) -> dict:
    unknown = set(fields) - ALLOWED_DRAFT_FIELDS
    if unknown:
        raise ValueError(f"不允许修改字段: {sorted(unknown)}")
    if fields.get("priority") not in (None, *ALLOWED_PRIORITIES):
        raise ValueError("priority 不合法")
    if "summary" in fields and not str(fields["summary"]).strip():
        raise ValueError("summary 不能为空")
    return fields


async def upsert_draft(session: AsyncSession, *, tenant_id: str, thread_id: UUID,
                       user_id: str, fields: dict, extracted_fields: dict | None = None) -> TicketDraft:
    validate_draft_fields(fields)
    draft = (await session.scalars(select(TicketDraft).where(TicketDraft.thread_id == thread_id)
                                   .with_for_update())).one_or_none()
    if draft is None:
        draft = TicketDraft(tenant_id=tenant_id, thread_id=thread_id, user_id=user_id,
                            fields=dict(fields), extracted_fields=extracted_fields or {}, status="PENDING")
        session.add(draft)
    else:
        draft.fields = {**(draft.fields or {}), **fields}
        if extracted_fields is not None:
            draft.extracted_fields = extracted_fields
        draft.status = "PENDING"
    await session.flush()
    return draft


async def get_draft(session: AsyncSession, thread_id: UUID) -> TicketDraft | None:
    return (await session.scalars(select(TicketDraft).where(TicketDraft.thread_id == thread_id))).one_or_none()

