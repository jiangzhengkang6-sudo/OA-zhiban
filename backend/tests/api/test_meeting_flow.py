import pytest
from sqlalchemy import text

from app.core.context import CurrentUser
from app.db.session import async_session_factory, engine
from app.schemas.meeting import MeetingInput
from app.services import meeting_service


@pytest.fixture
async def meeting_db(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE meeting_decision, meeting_draft_version, meeting_segment, meeting_source, meeting_record RESTART IDENTITY CASCADE"))
    async with async_session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_meeting_service_flow_is_platform_only_and_versioned(meeting_db):
    actor = CurrentUser(user_id="u_emp_001", tenant_id="t_001", roles=["employee"])
    created = await meeting_service.create_meeting(meeting_db, actor, MeetingInput(title="周会", content="项目进展已同步。下周完成验收。"))
    assert created.status == "CREATED"
    generated = await meeting_service.generate_draft(meeting_db, actor, created.meeting_id)
    assert generated.status == "DRAFT_READY"
    edited = await meeting_service.save_draft(meeting_db, actor, created.meeting_id, {
        "summary": "项目进展和验收计划",
        "topics": ["项目进展"],
        "decisions": [],
        "action_items": [{"title": "完成验收", "source_refs": [generated.segments[1].segment_id]}],
        "source_refs": [item.segment_id for item in generated.segments],
    })
    assert edited.status == "REVIEWING"
    confirmed = await meeting_service.decide(meeting_db, actor, created.meeting_id, "confirm", None, "confirm-1")
    assert confirmed.status == "CONFIRMED"
    assert confirmed.external_writes is False
    replay = await meeting_service.decide(meeting_db, actor, created.meeting_id, "confirm", None, "confirm-1")
    assert replay.status == "CONFIRMED"


@pytest.mark.asyncio
async def test_meeting_service_rejects_cross_tenant_and_idempotency_conflict(meeting_db):
    owner = CurrentUser(user_id="u_emp_001", tenant_id="t_001", roles=["employee"])
    other = CurrentUser(user_id="u_emp_002", tenant_id="t_002", roles=["employee"])
    created = await meeting_service.create_meeting(meeting_db, owner, MeetingInput(title="周会", content="讨论完成。", idempotency_key="meeting-1"))
    with pytest.raises(Exception):
        await meeting_service.get_meeting(meeting_db, other, created.meeting_id)
    await meeting_service.generate_draft(meeting_db, owner, created.meeting_id)
    await meeting_service.decide(meeting_db, owner, created.meeting_id, "confirm", None, "decision-1")
    with pytest.raises(Exception, match="幂等"):
        await meeting_service.decide(meeting_db, owner, created.meeting_id, "reject", "改载荷", "decision-1")
