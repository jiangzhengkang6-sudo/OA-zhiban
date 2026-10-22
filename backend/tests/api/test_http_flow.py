"""
OA 智能体管理系统 - HTTP 接口契约测试。

通过 httpx ASGI 传输走完整 HTTP 链路（会话→消息→查询→审批→恢复），验证 API、
中间件（trace/auth）、审计与图集成的端到端正确性，对应 AC-MVP 相关验收。
"""

import httpx
import pytest
from sqlalchemy import text

from app.db.session import async_session_factory, engine
from app.main import app as fastapi_app


@pytest.fixture
async def client(graph_ready):
    """提供隔离的 HTTP 客户端（每个测试前清空业务表）。

    Yields:
        httpx.AsyncClient: 走 ASGI 传输的客户端。
    """
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE agent_thread, agent_message, precheck_result, human_decision, "
            "ticket_record, ticket_assignment_rule, ticket_context, audit_event, agent_policy, policy_version, knowledge_chunk, knowledge_document, "
            "approval_decision, approval_node, approval_instance "
                ", meeting_decision, meeting_draft_version, meeting_segment, meeting_source, meeting_record "
            "RESTART IDENTITY CASCADE"
        ))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def emp_headers() -> dict:
    """员工请求头。"""
    return {"Authorization": "Bearer mock:u_emp_001"}


@pytest.fixture
def mgr_headers() -> dict:
    """审批人请求头。"""
    return {"Authorization": "Bearer mock:u_mgr_001"}


@pytest.mark.asyncio
async def test_faq_without_evidence_hands_off_without_ticket_draft(client, emp_headers):
    created = await client.post("/api/agent/threads", json={"scene": "faq"}, headers=emp_headers)
    assert created.status_code == 200
    tid = created.json()["data"]["thread_id"]
    sent = await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "年假需要提前多久提交？"}, headers=emp_headers,
    )
    assert sent.status_code == 200, sent.text
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["scene"] == "faq"
    assert detail["handoff"]["reason_code"] == "FAQ_UNCERTAIN"
    assert detail["ticket_draft"] is None
    assert detail["ticket"] is None


@pytest.mark.asyncio
async def test_explicit_faq_human_request_has_distinct_reason(client, emp_headers):
    created = await client.post("/api/agent/threads", json={"scene": "faq"}, headers=emp_headers)
    tid = created.json()["data"]["thread_id"]
    sent = await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "转人工"}, headers=emp_headers,
    )
    assert sent.status_code == 200, sent.text
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["handoff"]["reason_code"] == "FAQ_HUMAN_REQUEST"
    assert detail["ticket_draft"] is None


@pytest.mark.asyncio
async def test_model_unavailable_preserves_message_and_allows_new_attempt(client, emp_headers, monkeypatch):
    from app.core.enums import ErrorCode
    from app.graph.graph_service import runtime
    from app.llm.compatible import ProviderUnavailable

    created = await client.post("/api/agent/threads", json={"scene": "faq"}, headers=emp_headers)
    tid = created.json()["data"]["thread_id"]
    original_invoke = runtime.invoke

    async def unavailable(*args, **kwargs):
        raise ProviderUnavailable("private provider response test-secret")

    monkeypatch.setattr(runtime, "invoke", unavailable)
    transport = httpx.ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    payload = {"content": "年假需要提前多久提交？", "idempotency_key": "model-timeout"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as error_client:
        sent = await error_client.post(f"/api/agent/threads/{tid}/messages", json=payload, headers=emp_headers)
    assert sent.status_code == 502, sent.text
    assert sent.json()["code"] == ErrorCode.DEPENDENCY_FAILED.value
    assert "模型服务" in sent.json()["message"]
    assert "test-secret" not in sent.text
    assert "private provider" not in sent.text
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["status"] == "PAUSED"
    assert detail["error"]["code"] == ErrorCode.DEPENDENCY_FAILED.value
    assert len(detail["messages"]) == 1
    replay = await client.post(f"/api/agent/threads/{tid}/messages", json=payload, headers=emp_headers)
    assert replay.status_code == 200
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert len(detail["messages"]) == 1
    monkeypatch.setattr(runtime, "invoke", original_invoke)
    payload["idempotency_key"] = "model-recovered"
    recovered = await client.post(f"/api/agent/threads/{tid}/messages", json=payload, headers=emp_headers)
    assert recovered.status_code == 200, recovered.text
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["status"] == "WAITING_HUMAN"
    assert detail["error"] is None
    assert detail["handoff"]["reason_code"] == "FAQ_UNCERTAIN"


@pytest.mark.asyncio
async def test_leave_full_flow(client, emp_headers, mgr_headers):
    """请假闭环：创建会话→发消息→中断→批准→状态更新。"""
    r = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-OK-001"},
        headers=emp_headers,
    )
    assert r.json()["code"] == "0"
    tid = r.json()["data"]["thread_id"]

    r = await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "提交请假申请"},
        headers=emp_headers,
    )
    assert r.json()["data"]["status"] == "WAITING_HUMAN"
    assert r.json()["data"]["next_action"] == "waiting_human"

    r = await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)
    detail = r.json()["data"]
    assert (detail.get("precheck") or {}).get("passed") is True
    interrupt_id = detail.get("current_interrupt_id")
    assert interrupt_id, "应有 pending 中断"

    # 审批人可以查看审批链中的请假任务详情，但不能以员工身份写入消息。
    r = await client.get(f"/api/agent/threads/{tid}", headers=mgr_headers)
    assert r.status_code == 200
    assert r.json()["data"]["approval_route"]["nodes"][0]["approver_id"] == "u_mgr_001"

    r = await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "审批人不能代替员工发送消息"},
        headers=mgr_headers,
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/agent/interrupts/{interrupt_id}/resume",
        json={"action": "approve", "comment": "同意"},
        headers=mgr_headers,
    )
    assert r.json()["data"]["status"] == "WAITING_HUMAN"
    next_detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert next_detail["active_approval_node"]["approver_id"] == "u_mgr_002"
    assert next_detail["approval_status"] == "ACTIVE"
    assert next_detail["approval_nodes"][0]["status"] == "APPROVED"
    assert next_detail["current_interrupt_id"]
    assert next_detail["current_interrupt_id"] != interrupt_id
    final = await client.post(
        f"/api/agent/interrupts/{next_detail['current_interrupt_id']}/resume",
        json={"action": "approve", "comment": "二级同意"},
        headers={"Authorization": "Bearer mock:u_mgr_002"},
    )
    assert final.json()["data"]["status"] == "APPROVED"
    finished = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert finished["approval_status"] == "APPROVED"
    assert finished["approval_nodes"][1]["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_second_approver_cannot_bypass_first_node(client, emp_headers):
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    response = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert response.status_code in {403, 409}
    assert (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]["status"] == "WAITING_HUMAN"


@pytest.mark.asyncio
async def test_leave_decision_replay_does_not_advance_next_node(client, emp_headers, mgr_headers):
    from app.models.approval_decision import ApprovalDecision
    from sqlalchemy import func, select
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    first_id = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]["current_interrupt_id"]
    url = f"/api/agent/interrupts/{first_id}/resume"
    payload = {"action": "approve", "comment": "同意", "idempotency_key": f"approve-{tid}"}
    first = await client.post(url, json=payload, headers=mgr_headers)
    assert first.status_code == 200
    again = await client.post(url, json=payload, headers=mgr_headers)
    assert again.status_code == 200
    assert again.json()["data"]["status"] == "WAITING_HUMAN"
    changed = await client.post(url, json={**payload, "comment": "变更"}, headers=mgr_headers)
    assert changed.status_code == 409
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["active_approval_node"]["approver_id"] == "u_mgr_002"
    async with async_session_factory() as db:
        assert (await db.scalar(select(func.count()).select_from(ApprovalDecision))) == 1


@pytest.mark.asyncio
async def test_scheduler_nudges_each_current_node_once(client, emp_headers, mgr_headers):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.adapters.factory import get_adapter
    from app.models.approval_node import ApprovalNode
    from app.services.scheduler import _tick
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    async with async_session_factory() as db:
        node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.approver_id == "u_mgr_001", ApprovalNode.status == "ACTIVE"))).one()
        node.waiting_since = datetime.now(timezone.utc) - timedelta(minutes=8)
        await db.commit()
    adapter = get_adapter()
    before = len(adapter._state["notifications"])
    await _tick()
    await _tick()
    assert [n["user_id"] for n in adapter._state["notifications"][before:]] == ["u_mgr_001"]
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
                      json={"action": "approve"}, headers=mgr_headers)
    async with async_session_factory() as db:
        node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.approver_id == "u_mgr_002", ApprovalNode.status == "ACTIVE"))).one()
        node.waiting_since = datetime.now(timezone.utc) - timedelta(minutes=8)
        await db.commit()
    await _tick()
    assert [n["user_id"] for n in adapter._state["notifications"][before:]] == ["u_mgr_001", "u_mgr_002"]


@pytest.mark.asyncio
async def test_escalation_advances_to_configured_next_approver(client, emp_headers):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.approval_node import ApprovalNode
    from app.services.scheduler import _tick
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    async with async_session_factory() as db:
        node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.approver_id == "u_mgr_001", ApprovalNode.status == "ACTIVE"))).one()
        node.waiting_since = datetime.now(timezone.utc) - timedelta(minutes=20)
        await db.commit()
    await _tick()  # reminder is recorded first, even when both thresholds passed
    await _tick()
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["active_approval_node"]["approver_id"] == "u_mgr_002"
    assert detail["approval_nodes"][0]["status"] == "ESCALATED"
    forbidden = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_001"})
    assert forbidden.status_code in (403, 409)


@pytest.mark.asyncio
async def test_edit_then_recheck_keeps_current_approver(client, emp_headers, mgr_headers):
    from app.adapters.factory import get_adapter
    adapter = get_adapter()
    original_reason = adapter.get_leave_case("LV-OK-001").reason
    try:
        r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
        tid = r.json()["data"]["thread_id"]
        await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
        first = (await client.get(f"/api/agent/threads/{tid}", headers=mgr_headers)).json()["data"]
        updated_reason = f"{original_reason}-补充说明"
        result = await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
            json={"action": "edit", "comment": "补充必要信息", "edited_data": {"reason": updated_reason}}, headers=mgr_headers)
        assert result.status_code == 200
        detail = (await client.get(f"/api/agent/threads/{tid}", headers=mgr_headers)).json()["data"]
        assert detail["status"] == "WAITING_HUMAN"
        assert detail["active_approval_node"]["approver_id"] == "u_mgr_001"
        assert detail["approval_decisions"][0]["edited_data"]["reason"]["old"] == original_reason
        assert detail["form_snapshot"]["reason"] == updated_reason
    finally:
        adapter.update_leave_case("LV-OK-001", {"reason": original_reason})


@pytest.mark.asyncio
async def test_failed_final_oa_write_pauses_without_approval(client, emp_headers, mgr_headers, monkeypatch):
    from app.adapters.factory import get_adapter
    from app.adapters.oa_adapter import OAResult
    from app.models.approval_instance import ApprovalInstance
    from sqlalchemy import select
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers=mgr_headers)
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    monkeypatch.setattr(get_adapter(), "create_or_update_approval", lambda cmd: OAResult(
        success=False, request_id="", idempotency_key=cmd.idempotency_key, status="failed"))
    failed = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert failed.status_code == 502
    after = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert after["status"] == "PAUSED"
    assert after["approval_recovery_action"] == "reconcile"
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalInstance))).one().status == "PENDING_WRITE"


@pytest.mark.asyncio
async def test_concurrent_identical_decisions_resume_graph_once(client, emp_headers, mgr_headers, monkeypatch):
    import asyncio
    from app.graph.graph_service import runtime
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    old_id = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]["current_interrupt_id"]
    original_resume = runtime.resume
    calls = 0
    async def slow_resume(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.08)
        return await original_resume(*args, **kwargs)
    monkeypatch.setattr(runtime, "resume", slow_resume)
    url = f"/api/agent/interrupts/{old_id}/resume"
    payload = {"action": "approve", "comment": "同意", "idempotency_key": f"race-{tid}"}
    first, second = await asyncio.gather(client.post(url, json=payload, headers=mgr_headers),
                                          client.post(url, json=payload, headers=mgr_headers))
    assert first.status_code == second.status_code == 200
    assert calls == 1
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["active_approval_node"]["approver_id"] == "u_mgr_002"


@pytest.mark.asyncio
async def test_escalation_race_with_approval_never_pauses_active_next_node(client, emp_headers, mgr_headers, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.approval_node import ApprovalNode
    from app.services import scheduler as scheduler_service
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    async with async_session_factory() as db:
        node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.status == "ACTIVE"))).one()
        node.waiting_since = datetime.now(timezone.utc) - timedelta(minutes=20)
        node.last_nudge_at = datetime.now(timezone.utc) - timedelta(minutes=15)
        await db.commit()
    entered = asyncio.Event()
    original_escalate = scheduler_service._escalate
    async def slow_escalate(*args, **kwargs):
        entered.set()
        await asyncio.sleep(0.1)
        return await original_escalate(*args, **kwargs)
    monkeypatch.setattr(scheduler_service, "_escalate", slow_escalate)
    scheduler = asyncio.create_task(scheduler_service._tick())
    await entered.wait()
    approval = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers=mgr_headers)
    await scheduler
    assert approval.status_code in {200, 403, 409}
    state = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert state["approval_status"] == "ACTIVE"
    assert state["active_approval_node"]["approver_id"] == "u_mgr_002"


@pytest.mark.asyncio
async def test_reject_still_completes_when_summary_model_unavailable(client, emp_headers, mgr_headers, monkeypatch):
    from app.llm.base import LLMFactory
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    monkeypatch.setattr(LLMFactory, "get_llm", lambda: (_ for _ in ()).throw(RuntimeError("模型不可用")))
    response = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={"action": "reject", "comment": "材料不充分"}, headers=mgr_headers)
    assert response.status_code == 200
    after = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert after["status"] == "REJECTED"
    assert after["approval_status"] == "REJECTED"


@pytest.mark.asyncio
async def test_legacy_pending_leave_adopts_route_without_losing_thread(client, emp_headers, mgr_headers):
    from sqlalchemy import delete
    from app.models.approval_node import ApprovalNode
    from app.models.approval_instance import ApprovalInstance
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    before = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    async with async_session_factory() as db:
        await db.execute(delete(ApprovalNode))
        await db.execute(delete(ApprovalInstance))
        await db.commit()
    response = await client.post(f"/api/agent/interrupts/{before['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers=mgr_headers)
    assert response.status_code == 200
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["active_approval_node"]["approver_id"] == "u_mgr_002"


@pytest.mark.asyncio
async def test_lost_oa_response_reconciles_using_original_key(client, emp_headers, mgr_headers, monkeypatch):
    from app.adapters.factory import get_adapter
    adapter = get_adapter()
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers=mgr_headers)
    second = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    original = adapter.create_or_update_approval
    def lost_response(command):
        original(command)
        raise TimeoutError("响应丢失")
    monkeypatch.setattr(adapter, "create_or_update_approval", lost_response)
    failed = await client.post(f"/api/agent/interrupts/{second['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert failed.status_code == 502
    paused = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert paused["approval_recovery_action"] == "reconcile"
    monkeypatch.setattr(adapter, "create_or_update_approval", original)
    recovered = await client.post(f"/api/approvals/threads/{tid}/reconcile",
        headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert recovered.status_code == 200
    after = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert after["status"] == "APPROVED"
    assert after["approval_status"] == "APPROVED"
    from app.graph.graph_service import runtime
    snapshot = await runtime.get_state(tid)
    assert snapshot.next == (), f"审批权威已完成但编排仍待执行: {snapshot.next}"


@pytest.mark.asyncio
async def test_uncertain_nudge_never_resends_after_scheduler_restart(client, emp_headers, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.approval_node import ApprovalNode
    from app.models.idempotency_record import IdempotencyRecord
    from app.services.scheduler import _tick
    from app.tools import notify_tools
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    async with async_session_factory() as db:
        node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.status == "ACTIVE"))).one()
        node.waiting_since = datetime.now(timezone.utc) - timedelta(minutes=8)
        node_id = node.id
        await db.commit()
    calls = 0
    async def unknown(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("通知响应未知")
    monkeypatch.setattr(notify_tools, "notify_user", unknown)
    await _tick()
    await _tick()
    assert calls == 1
    async with async_session_factory() as db:
        record = (await db.scalars(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == f"nudge-{node_id}"))).one()
        assert record.status == "UNKNOWN"
        node = await db.get(ApprovalNode, node_id)
        assert node.last_nudge_at is None
        from app.models.agent_thread import AgentThread
        thread = await db.get(AgentThread, tid)
        assert thread.status == "PAUSED"


@pytest.mark.asyncio
async def test_legacy_waiting_without_interrupt_requires_manual_reconciliation(client, emp_headers):
    from app.models.agent_thread import AgentThread
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    async with async_session_factory() as db:
        thread = await db.get(AgentThread, tid)
        thread.status = "WAITING_HUMAN"
        await db.commit()
    detail = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert detail["error"]["code"] == "LEGACY_RECONCILE"
    assert detail["current_interrupt_id"] is None


@pytest.mark.asyncio
async def test_preflight_denial_can_retry_without_reissuing_unknown_write(client, emp_headers, mgr_headers, monkeypatch):
    from app.graph.nodes import leave_nodes
    from app.models.idempotency_record import IdempotencyRecord
    from sqlalchemy import select
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
                      json={"action": "approve"}, headers=mgr_headers)
    second = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    original = leave_nodes.authorize_tool
    def denied(*args, **kwargs):
        raise RuntimeError("角色临时不可验证")
    monkeypatch.setattr(leave_nodes, "authorize_tool", denied)
    failed = await client.post(f"/api/agent/interrupts/{second['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert failed.status_code == 502
    paused = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert paused["approval_recovery_action"] == "retry"
    async with async_session_factory() as db:
        assert (await db.scalars(select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == f"approval-{tid}"))).one_or_none() is None
    monkeypatch.setattr(leave_nodes, "authorize_tool", original)
    retry = await client.post(f"/api/approvals/threads/{tid}/retry-write",
        headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert retry.status_code == 200
    assert retry.json()["data"]["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_final_write_rejects_changed_authoritative_form(client, emp_headers, mgr_headers):
    from app.adapters.factory import get_adapter
    adapter = get_adapter()
    original = adapter.get_leave_case("LV-OK-001").reason
    try:
        r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
        tid = r.json()["data"]["thread_id"]
        await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
        first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
        await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
            json={"action": "approve"}, headers=mgr_headers)
        adapter.update_leave_case("LV-OK-001", {"reason": "未经重新预检的修改"})
        second = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
        response = await client.post(f"/api/agent/interrupts/{second['current_interrupt_id']}/resume",
            json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
        assert response.status_code == 502
        after = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
        assert after["status"] == "PAUSED"
        assert after["approval_recovery_action"] == "retry"
        assert adapter.get_approval_result(f"approval-{tid}") is None
        from app.models.idempotency_record import IdempotencyRecord
        from sqlalchemy import select
        async with async_session_factory() as db:
            assert (await db.scalars(select(IdempotencyRecord).where(
                IdempotencyRecord.idempotency_key == f"approval-{tid}"))).one_or_none() is None
    finally:
        adapter.update_leave_case("LV-OK-001", {"reason": original})


@pytest.mark.asyncio
async def test_reconcile_does_not_allow_unrelated_tenant_member_after_approval(client, emp_headers, mgr_headers):
    r = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = r.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers=mgr_headers)
    second = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{second['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
    unauthorized = await client.post(f"/api/approvals/threads/{tid}/reconcile",
        headers={"Authorization": "Bearer mock:u_cs_001"})
    assert unauthorized.status_code == 403


@pytest.mark.asyncio
async def test_legacy_pending_without_prechecked_form_requires_manual_review(client, emp_headers):
    from app.models.agent_thread import AgentThread
    from app.services.approval_service import adopt_legacy_pending, get_instance
    from app.core.errors import AppException

    response = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = response.json()["data"]["thread_id"]
    async with async_session_factory() as db:
        thread = await db.get(AgentThread, tid)
        thread.current_interrupt_id = "legacy-interrupt"
        with pytest.raises(AppException) as error:
            await adopt_legacy_pending(db, thread, {"precheck": {"passed": True},
                "approval_route": {"business_id": "LV-OK-001", "nodes": [
                    {"order": 1, "approver_id": "u_mgr_001"}]}})
        assert error.value.http_status == 409
        assert await get_instance(db, thread.id) is None


@pytest.mark.asyncio
async def test_lost_outcome_notification_pauses_without_duplicate_delivery(client, emp_headers, mgr_headers, monkeypatch):
    from app.adapters.factory import get_adapter
    from app.models.idempotency_record import IdempotencyRecord
    from sqlalchemy import select

    adapter = get_adapter()
    created = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = created.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
    first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume", json={"action": "approve"}, headers=mgr_headers)
    second = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    original = adapter.notify

    def lost_response(command):
        original(command)
        raise TimeoutError("通知成功但响应丢失")

    monkeypatch.setattr(adapter, "notify", lost_response)
    failed = await client.post(f"/api/agent/interrupts/{second['current_interrupt_id']}/resume",
        json={"action": "approve"}, headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert failed.status_code == 502
    paused = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
    assert paused["status"] == "PAUSED"
    async with async_session_factory() as db:
        record = (await db.scalars(select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == f"notify-{tid}-approved"))).one()
        assert record.status == "UNKNOWN"
    delivered = len([n for n in adapter._state["notifications"] if n.get("idempotency_key") == f"notify-{tid}-approved"])
    assert delivered == 1
    monkeypatch.setattr(adapter, "notify", original)
    recovered = await client.post(f"/api/approvals/threads/{tid}/reconcile",
        headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert recovered.status_code == 200
    assert len([n for n in adapter._state["notifications"] if n.get("idempotency_key") == f"notify-{tid}-approved"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('recovery', ['confirmed', 'missing', 'wrong_key', 'changed_form', 'unrelated', 'next_approver'])
async def test_edit_write_lost_response_reconciles_without_reapplying(client, emp_headers, mgr_headers, monkeypatch, recovery):
    from app.adapters.factory import get_adapter
    from app.models.idempotency_record import IdempotencyRecord
    from sqlalchemy import select

    adapter = get_adapter()
    old_reason = adapter.get_leave_case("LV-OK-001").reason
    created = await client.post("/api/agent/threads", json={"scene": "leave", "business_id": "LV-OK-001"}, headers=emp_headers)
    tid = created.json()["data"]["thread_id"]
    try:
        await client.post(f"/api/agent/threads/{tid}/messages", json={"content": "提交请假申请"}, headers=emp_headers)
        first = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
        original = adapter.edit_leave_case

        def lost_response(command):
            original(command)
            raise TimeoutError("表单已改但响应丢失")

        monkeypatch.setattr(adapter, "edit_leave_case", lost_response)
        failed = await client.post(f"/api/agent/interrupts/{first['current_interrupt_id']}/resume",
            json={"action": "edit", "comment": "补充原因", "edited_data": {"reason": "家庭事务补充说明"}}, headers=mgr_headers)
        assert failed.status_code == 502
        paused = (await client.get(f"/api/agent/threads/{tid}", headers=emp_headers)).json()["data"]
        assert paused["status"] == "PAUSED"
        async with async_session_factory() as db:
            record = (await db.scalars(select(IdempotencyRecord).where(
                IdempotencyRecord.idempotency_key == f"edit-{tid}-{first['current_interrupt_id']}"))).one()
            assert record.status == "UNKNOWN"
        assert adapter.get_leave_case("LV-OK-001").reason == "家庭事务补充说明"
        def no_reapply(command):
            pytest.fail("对账不得再次编辑 OA 表单")

        monkeypatch.setattr(adapter, "edit_leave_case", no_reapply)
        if recovery == 'missing':
            monkeypatch.setattr(adapter, 'get_leave_edit_result', lambda key: None)
        elif recovery == 'wrong_key':
            lookup = adapter.get_leave_edit_result
            monkeypatch.setattr(adapter, 'get_leave_edit_result',
                lambda key: lookup(key).model_copy(update={'idempotency_key': 'another-request'}))
        elif recovery == 'changed_form':
            adapter.update_leave_case('LV-OK-001', {'reason': '外部再次修改'})
        headers = ({'Authorization': 'Bearer mock:u_cs_001'} if recovery == 'unrelated' else
                   {'Authorization': 'Bearer mock:u_mgr_002'} if recovery == 'next_approver' else mgr_headers)
        recovered = await client.post(f"/api/approvals/threads/{tid}/reconcile",
            headers=headers)
        if recovery != 'confirmed':
            assert recovered.status_code == (403 if recovery in {'unrelated', 'next_approver'} else 502)
            detail = (await client.get(f'/api/agent/threads/{tid}', headers=emp_headers)).json()['data']
            assert detail['status'] == 'PAUSED'
            async with async_session_factory() as db:
                record = (await db.scalars(select(IdempotencyRecord).where(
                    IdempotencyRecord.idempotency_key == f"edit-{tid}-{first['current_interrupt_id']}"))).one()
                assert record.status == 'UNKNOWN'
            return
        assert recovered.status_code == 200, recovered.json()
        assert adapter.get_leave_case("LV-OK-001").reason == "家庭事务补充说明"
        detail = (await client.get(f'/api/agent/threads/{tid}', headers=emp_headers)).json()['data']
        assert detail['status'] == 'WAITING_HUMAN'
        assert detail['active_approval_node']['approver_id'] == 'u_mgr_001'
        assert detail['current_interrupt_id'] != first['current_interrupt_id']
        assert detail['precheck']['passed'] is True
        async with async_session_factory() as db:
            record = (await db.scalars(select(IdempotencyRecord).where(
                IdempotencyRecord.idempotency_key == f"edit-{tid}-{first['current_interrupt_id']}"))).one()
            assert record.status == 'SUCCEEDED'
        approved = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
            json={'action': 'approve'}, headers=mgr_headers)
        assert approved.status_code == 200
    finally:
        adapter.update_leave_case("LV-OK-001", {"reason": old_reason})


@pytest.mark.asyncio
async def test_leave_needs_fix_flow(client, emp_headers):
    """病假缺附件：预检未通过，状态 NEEDS_FIX。"""
    r = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-NOATT-001"},
        headers=emp_headers,
    )
    tid = r.json()["data"]["thread_id"]
    r = await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "提交请假申请"},
        headers=emp_headers,
    )
    assert r.json()["data"]["status"] == "NEEDS_FIX"


@pytest.mark.asyncio
async def test_leave_thread_requires_existing_owned_business_id(client, emp_headers):
    """请假会话必须关联当前员工在 OA 中已存在的请假单。"""
    missing = await client.post(
        "/api/agent/threads",
        json={"scene": "leave"},
        headers=emp_headers,
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "10001"

    unknown = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-UNKNOWN-001"},
        headers=emp_headers,
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "40401"


@pytest.mark.asyncio
async def test_precheck_does_not_expose_another_employee_leave(client, mgr_headers):
    response = await client.post("/api/approvals/LV-OK-001/precheck",
        json={"business_id": "LV-OK-001"}, headers=mgr_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_thread_idempotent(client, emp_headers):
    """相同业务单据号重复创建会话，返回已有会话。"""
    r1 = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-OK-001"},
        headers=emp_headers,
    )
    r2 = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-OK-001"},
        headers=emp_headers,
    )
    assert r1.json()["data"]["thread_id"] == r2.json()["data"]["thread_id"]


@pytest.mark.asyncio
async def test_permission_denied(client, emp_headers):
    """员工访问审计接口应被拒绝。"""
    r = await client.get("/api/audit/events", headers=emp_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_employee_cannot_approve_leave(client, emp_headers):
    """请假审批只能由审批链中的人员提交。"""
    r = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-OK-001"},
        headers=emp_headers,
    )
    tid = r.json()["data"]["thread_id"]
    r = await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "提交请假申请", "idempotency_key": "leave-auth-001"},
        headers=emp_headers,
    )
    interrupt_id = (await client.get(
        f"/api/agent/threads/{tid}", headers=emp_headers
    )).json()["data"]["current_interrupt_id"]
    r = await client.post(
        f"/api/agent/interrupts/{interrupt_id}/resume",
        json={"action": "approve"},
        headers=emp_headers,
    )
    assert r.status_code == 403
    assert r.json()["code"] == "40301"


@pytest.mark.asyncio
async def test_message_idempotency(client, emp_headers):
    """相同消息幂等键不能重复写入和推进图。"""
    r = await client.post(
        "/api/agent/threads",
        json={"scene": "ticket"},
        headers=emp_headers,
    )
    tid = r.json()["data"]["thread_id"]
    payload = {"content": "我的电脑无法开机", "idempotency_key": "msg-idem-001"}
    r1 = await client.post(
        f"/api/agent/threads/{tid}/messages", json=payload, headers=emp_headers
    )
    r2 = await client.post(
        f"/api/agent/threads/{tid}/messages", json=payload, headers=emp_headers
    )
    assert r1.json()["data"]["message_id"] == r2.json()["data"]["message_id"]
    detail = (await client.get(
        f"/api/agent/threads/{tid}", headers=emp_headers
    )).json()["data"]
    assert len(detail["messages"]) == 1


@pytest.mark.asyncio
async def test_ticket_requires_confirmed_thread(client, emp_headers):
    """直接工单接口不能绕过会话确认门。"""
    r = await client.post(
        "/api/tickets",
        json={
            "category": "IT",
            "priority": "high",
            "summary": "绕过确认创建",
            "idempotency_key": "unsafe-ticket-001",
        },
        headers=emp_headers,
    )
    assert r.status_code == 422
    assert r.json()["code"] == "42201"


@pytest.mark.asyncio
async def test_ticket_rejects_approval_action(client, emp_headers):
    """工单确认中断不能被 approve 等审批动作误处理为取消。"""
    r = await client.post(
        "/api/agent/threads",
        json={"scene": "ticket"},
        headers=emp_headers,
    )
    tid = r.json()["data"]["thread_id"]
    await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "电脑无法开机", "idempotency_key": "ticket-action-001"},
        headers=emp_headers,
    )
    detail = (await client.get(
        f"/api/agent/threads/{tid}", headers=emp_headers
    )).json()["data"]
    r = await client.post(
        f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={"action": "approve"},
        headers=emp_headers,
    )
    assert r.status_code == 422
    assert r.json()["code"] == "42201"


@pytest.mark.asyncio
async def test_ticket_result_visible_after_confirm(client, emp_headers):
    """工单确认后会话详情必须返回工单号。"""
    r = await client.post(
        "/api/agent/threads",
        json={"scene": "ticket"},
        headers=emp_headers,
    )
    tid = r.json()["data"]["thread_id"]
    await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "我的电脑无法开机", "idempotency_key": "ticket-visible-001"},
        headers=emp_headers,
    )
    detail = (await client.get(
        f"/api/agent/threads/{tid}", headers=emp_headers
    )).json()["data"]
    interrupt_id = detail["current_interrupt_id"]
    r = await client.post(
        f"/api/agent/interrupts/{interrupt_id}/resume",
        json={"action": "confirm"},
        headers=emp_headers,
    )
    assert r.status_code == 200
    detail = (await client.get(
        f"/api/agent/threads/{tid}", headers=emp_headers
    )).json()["data"]
    assert detail["ticket"]["ticket_id"].startswith("TK-")


@pytest.mark.asyncio
async def test_ticket_extraction_metadata_survives_draft_edit(client, emp_headers):
    created = await client.post('/api/agent/threads', json={'scene': 'ticket'}, headers=emp_headers)
    tid = created.json()['data']['thread_id']
    await client.post(f'/api/agent/threads/{tid}/messages',
        json={'content': '电脑无法开机'}, headers=emp_headers)
    draft = (await client.get(f'/api/tickets/drafts/{tid}', headers=emp_headers)).json()['data']
    assert 'missing_fields' in draft['extracted_fields']
    assert 'missing_fields' not in draft['fields']
    detail = (await client.get(f'/api/agent/threads/{tid}', headers=emp_headers)).json()['data']
    edited = await client.post(f"/api/agent/interrupts/{detail['current_interrupt_id']}/resume",
        json={'action': 'edit', 'edited_data': {'priority': 'high'}}, headers=emp_headers)
    assert edited.status_code == 200
    updated = (await client.get(f'/api/tickets/drafts/{tid}', headers=emp_headers)).json()['data']
    assert updated['fields']['priority'] == 'high'
    assert updated['extracted_fields'] == draft['extracted_fields']
    rejected = await client.patch(f'/api/tickets/drafts/{tid}',
        json={'fields': {'missing_fields': []}}, headers=emp_headers)
    assert rejected.status_code == 422
