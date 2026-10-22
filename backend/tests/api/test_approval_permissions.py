from uuid import uuid4
import pytest
from sqlalchemy import select
from app.adapters.factory import get_adapter
from app.db.session import async_session_factory
from app.models.approval_instance import ApprovalInstance
from app.models.approval_node import ApprovalNode
from app.services.approval_service import active_node, ensure_instance, record_decision, finalize_approval
from app.core.errors import AppException


@pytest.mark.asyncio
async def test_node_state_is_ordered_and_second_actor_is_blocked(graph_ready):
    tid = uuid4()
    route = get_adapter().get_approval_route("u_emp_001", get_adapter().get_leave_case("LV-OK-001")).model_dump()
    async with async_session_factory() as db:
        instance = await ensure_instance(db, tid, "t_001", "LV-OK-001", route)
        await db.commit()
        first = await active_node(db, tid)
        assert first.approver_id == "u_mgr_001"
        with pytest.raises(AppException):
            await record_decision(db, tid, "u_mgr_002", "approve", "越级", {}, "decision-2-"+str(tid))
        await db.rollback()
        progress = await record_decision(db, tid, "u_mgr_001", "approve", "同意", {}, "decision-1-"+str(tid))
        assert progress == "waiting_human"
        await db.commit()
        second = await active_node(db, tid)
        assert second.approver_id == "u_mgr_002"
        final = await record_decision(db, tid, "u_mgr_002", "approve", "同意", {}, "decision-2-"+str(tid))
        assert final == "pending_write"
        await db.commit()
        assert await active_node(db, tid) is None
        await finalize_approval(db, tid, "oa-request-001")
        await db.commit()
        assert (await db.scalars(select(ApprovalInstance).where(ApprovalInstance.thread_id == tid))).one().status == "APPROVED"


@pytest.mark.asyncio
async def test_edited_approval_requires_explicit_allowed_changes(graph_ready):
    tid = uuid4()
    route = get_adapter().get_approval_route("u_emp_001", get_adapter().get_leave_case("LV-OK-001")).model_dump()
    async with async_session_factory() as db:
        await ensure_instance(db, tid, "t_001", "LV-OK-001", route)
        await db.commit()
        with pytest.raises(AppException):
            await record_decision(db, tid, "u_mgr_001", "edit", "修改", {}, "edit-"+str(tid))
        with pytest.raises(AppException):
            await record_decision(db, tid, "u_mgr_001", "edit", "修改", {"user_id": "u_mgr_001"}, "edit-"+str(tid))
        await db.rollback()
        assert (await active_node(db, tid)).approver_id == "u_mgr_001"


@pytest.mark.asyncio
async def test_edit_decision_stores_before_after_difference(graph_ready):
    from app.models.approval_decision import ApprovalDecision
    tid = uuid4()
    route = get_adapter().get_approval_route("u_emp_001", get_adapter().get_leave_case("LV-OK-001")).model_dump()
    async with async_session_factory() as db:
        await ensure_instance(db, tid, "t_001", "LV-OK-001", route)
        await db.commit()
        await record_decision(db, tid, "u_mgr_001", "edit", "理由更准确", {"reason": "家庭照护"}, str(tid))
        await db.commit()
        decision = (await db.scalars(select(ApprovalDecision).where(ApprovalDecision.instance_id ==
            (await db.scalars(select(ApprovalInstance).where(ApprovalInstance.thread_id == tid))).one().id))).one()
        assert decision.edited_data["reason"] == {"old": "家庭事务", "new": "家庭照护"}
        assert (await active_node(db, tid)).approver_id == "u_mgr_001"


@pytest.mark.asyncio
async def test_rejection_stores_structured_reason(graph_ready):
    from app.models.approval_decision import ApprovalDecision
    tid = uuid4()
    route = get_adapter().get_approval_route("u_emp_001", get_adapter().get_leave_case("LV-OK-001")).model_dump()
    async with async_session_factory() as db:
        instance = await ensure_instance(db, tid, "t_001", "LV-OK-001", route)
        await db.commit()
        assert await record_decision(db, tid, "u_mgr_001", "reject", "材料不充分",
                                     {"reason_category": "materials"}, f"reject-{tid}") == "rejected"
        await db.commit()
        decision = (await db.scalars(select(ApprovalDecision).where(ApprovalDecision.instance_id == instance.id))).one()
        assert decision.edited_data == {"reason_category": "materials"}


@pytest.mark.asyncio
async def test_rejection_rejects_unrecognized_reason_category(graph_ready):
    tid = uuid4()
    route = get_adapter().get_approval_route("u_emp_001", get_adapter().get_leave_case("LV-OK-001")).model_dump()
    async with async_session_factory() as db:
        await ensure_instance(db, tid, "t_001", "LV-OK-001", route)
        await db.commit()
        with pytest.raises(AppException):
            await record_decision(db, tid, "u_mgr_001", "reject", "不合规",
                                  {"reason_category": "invented"}, f"reject-{tid}")
