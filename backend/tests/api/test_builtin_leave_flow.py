"""B4 built-in leave application API contract tests."""

import httpx
import pytest
from sqlalchemy import select, text

from app.db.session import async_session_factory, engine
from app.main import app as fastapi_app
from app.models.approval_instance import ApprovalInstance
from app.models.approval_node import ApprovalNode
from app.models.agent_thread import AgentThread
from app.models.leave_application import LeaveApplication


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE agent_thread, agent_message, precheck_result, human_decision, "
            "ticket_record, ticket_assignment_rule, ticket_context, audit_event, agent_policy, policy_version, knowledge_chunk, knowledge_document, "
            "approval_decision, approval_node, approval_instance, human_queue_item, "
            "handoff_snapshot, ticket_draft, leave_attachment, leave_application_version, "
            "leave_application RESTART IDENTITY CASCADE"
        ))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def emp_headers():
    return {"Authorization": "Bearer mock:u_emp_001"}


@pytest.mark.asyncio
async def test_builtin_leave_draft_submit_and_version_diff(client, emp_headers):
    created = await client.post("/api/leaves", json={
        "leave_type": "annual",
        "start_at": "2026-10-20T09:00:00+08:00",
        "end_at": "2026-10-21T18:00:00+08:00",
        "reason": "家庭事务",
    }, headers=emp_headers)
    assert created.status_code == 200
    app = created.json()["data"]
    app_id = app["application_id"]
    assert app["status"] == "DRAFT"

    patched = await client.patch(f"/api/leaves/{app_id}", json={"reason": "家庭事务补充说明"},
                                 headers=emp_headers)
    assert patched.status_code == 200
    submitted = await client.post(f"/api/leaves/{app_id}/submit", headers=emp_headers)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["status"] == "SUBMITTED"
    assert submitted.json()["data"]["precheck"]["passed"] is True

    async with async_session_factory() as db:
        application = await db.get(LeaveApplication, app_id)
        assert application.thread_id is not None
        thread = await db.get(AgentThread, application.thread_id)
        assert thread is not None
        assert thread.business_id == application.business_id
        assert thread.status == "WAITING_HUMAN"
        instance = (await db.scalars(select(ApprovalInstance).where(
            ApprovalInstance.thread_id == thread.id))).one()
        assert instance.status == "ACTIVE"
        nodes = (await db.scalars(select(ApprovalNode).where(
            ApprovalNode.instance_id == instance.id).order_by(ApprovalNode.node_order))).all()
        assert [(node.node_order, node.approver_id, node.status) for node in nodes] == [
            (1, "u_mgr_001", "ACTIVE"), (2, "u_mgr_002", "PENDING")
        ]

    employee_tasks = await client.get("/api/tasks?scene=leave", headers=emp_headers)
    assert employee_tasks.status_code == 200
    assert any(item["business_id"] == app["business_id"]
               for item in employee_tasks.json()["data"]["items"])

    versions = await client.get(f"/api/leaves/{app_id}/versions", headers=emp_headers)
    assert versions.status_code == 200
    assert len(versions.json()["data"]) == 1
    assert versions.json()["data"][0]["version"] == 1


@pytest.mark.asyncio
async def test_builtin_leave_failed_precheck_stays_editable_and_no_approval(client, emp_headers, monkeypatch):
    created = await client.post("/api/leaves", json={
        "leave_type": "sick",
        "start_at": "2026-10-20T09:00:00+08:00",
        "end_at": "2026-10-20T18:00:00+08:00",
        "reason": "就医",
    }, headers=emp_headers)
    app_id = created.json()["data"]["application_id"]
    failed = await client.post(f"/api/leaves/{app_id}/submit", headers=emp_headers)
    assert failed.status_code == 200
    data = failed.json()["data"]
    assert data["status"] == "NEEDS_FIX"
    assert any(item["item"] == "attachment" and item["result"] == "fail"
               for item in data["precheck"]["items"])
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalInstance))).all() == []

    import io
    from PIL import Image
    from app.providers import file_scanner
    async def clean(content):
        return 'CLEAN'
    monkeypatch.setattr(file_scanner, 'scan_bytes', clean)
    from app.adapters.factory import get_adapter
    from app.adapters.oa_adapter import Balance
    monkeypatch.setattr(get_adapter(), 'get_leave_balance',
                        lambda *args: Balance(leave_type='sick', total=5, used=4, remaining=1))
    proof = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(proof, format='PNG')
    fixed = await client.post(f"/api/leaves/{app_id}/attachments",
                              files={'file': ('proof.png', proof.getvalue(), 'image/png')}, headers=emp_headers)
    assert fixed.status_code == 200
    resubmitted = await client.post(f"/api/leaves/{app_id}/submit", headers=emp_headers)
    assert resubmitted.status_code == 200
    assert resubmitted.json()["data"]["status"] == "SUBMITTED"
    versions = await client.get(f"/api/leaves/{app_id}/versions", headers=emp_headers)
    assert len(versions.json()["data"]) == 2


@pytest.mark.asyncio
async def test_builtin_leave_approval_task_is_visible_to_current_approver_only(client, emp_headers):
    created = await client.post("/api/leaves", json={
        "leave_type": "annual",
        "start_at": "2026-10-20T09:00:00+08:00",
        "end_at": "2026-10-21T18:00:00+08:00",
        "reason": "家庭事务",
    }, headers=emp_headers)
    app_id = created.json()["data"]["application_id"]
    await client.post(f"/api/leaves/{app_id}/submit", headers=emp_headers)

    manager = await client.get("/api/tasks?scene=leave&status=WAITING_HUMAN",
                               headers={"Authorization": "Bearer mock:u_mgr_001"})
    assert manager.status_code == 200
    item = next(item for item in manager.json()["data"]["items"]
                 if item["business_id"] == created.json()["data"]["business_id"])
    assert item["responsibility"]["user_id"] == "u_mgr_001"
    assert {"approve", "edit", "reject"}.issubset(item["available_actions"])

    second_manager = await client.get("/api/tasks?scene=leave&status=WAITING_HUMAN",
                                      headers={"Authorization": "Bearer mock:u_mgr_002"})
    assert second_manager.status_code == 200
    assert not any(item["business_id"] == created.json()["data"]["business_id"]
                   for item in second_manager.json()["data"]["items"])


@pytest.mark.asyncio
async def test_builtin_leave_decision_advances_ordered_nodes(client, emp_headers):
    created = await client.post("/api/leaves", json={
        "leave_type": "annual",
        "start_at": "2026-10-20T09:00:00+08:00",
        "end_at": "2026-10-21T18:00:00+08:00",
        "reason": "家庭事务",
    }, headers=emp_headers)
    app_id = created.json()["data"]["application_id"]
    await client.post(f"/api/leaves/{app_id}/submit", headers=emp_headers)

    first = await client.post(
        f"/api/leaves/{app_id}/decision",
        json={"action": "approve", "comment": "同意", "idempotency_key": "builtin-1"},
        headers={"Authorization": "Bearer mock:u_mgr_001"},
    )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "WAITING_HUMAN"

    second = await client.post(
        f"/api/leaves/{app_id}/decision",
        json={"action": "approve", "comment": "同意", "idempotency_key": "builtin-2"},
        headers={"Authorization": "Bearer mock:u_mgr_002"},
    )
    assert second.status_code == 200
    assert second.json()["data"]["status"] == "APPROVED"

    replay = await client.post(
        f"/api/leaves/{app_id}/decision",
        json={"action": "approve", "comment": "同意", "idempotency_key": "builtin-2"},
        headers={"Authorization": "Bearer mock:u_mgr_002"},
    )
    assert replay.status_code == 200


@pytest.mark.asyncio
async def test_builtin_leave_is_owner_scoped(client, emp_headers):
    created = await client.post("/api/leaves", json={
        "leave_type": "annual",
        "start_at": "2026-10-20T09:00:00+08:00",
        "end_at": "2026-10-21T18:00:00+08:00",
        "reason": "家庭事务",
    }, headers=emp_headers)
    app_id = created.json()["data"]["application_id"]
    other = await client.get(f"/api/leaves/{app_id}",
                             headers={"Authorization": "Bearer mock:u_cs_001"})
    assert other.status_code == 403


async def make_submitted(client, emp_headers):
    created = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-21T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    application_id = created.json()['data']['application_id']
    submitted = await client.post(f'/api/leaves/{application_id}/submit', headers=emp_headers)
    return submitted.json()['data']


@pytest.mark.asyncio
async def test_builtin_details_restore_materials_and_current_approver_scope(client, emp_headers):
    application = await make_submitted(client, emp_headers)
    tid = application['thread_id']
    detail = await client.get(f'/api/agent/threads/{tid}',
                              headers={'Authorization': 'Bearer mock:u_mgr_001'})
    assert detail.status_code == 200
    data = detail.json()['data']
    assert data['application_id'] == application['application_id']
    assert data['form_snapshot']['reason'] == '家庭事务'
    assert data['precheck']['passed'] is True
    assert len(data['approval_route']['nodes']) == 2
    second = await client.get(f'/api/agent/threads/{tid}',
                              headers={'Authorization': 'Bearer mock:u_mgr_002'})
    assert second.status_code == 403


@pytest.mark.asyncio
async def test_builtin_reject_modify_resubmit_preserves_versions_and_thread(client, emp_headers):
    application = await make_submitted(client, emp_headers)
    aid, tid = application['application_id'], application['thread_id']
    rejected = await client.post(f'/api/leaves/{aid}/decision', json={
        'action': 'reject', 'comment': '请调整时间', 'edited_data': {'reason_category': 'scheduling'},
        'idempotency_key': 'reject-v1',
    }, headers={'Authorization': 'Bearer mock:u_mgr_001'})
    assert rejected.status_code == 200
    patch = await client.patch(f'/api/leaves/{aid}', json={'reason': '调整后的原因'}, headers=emp_headers)
    assert patch.status_code == 200
    resubmitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert resubmitted.status_code == 200
    assert resubmitted.json()['data']['thread_id'] == tid
    versions = (await client.get(f'/api/leaves/{aid}/versions', headers=emp_headers)).json()['data']
    assert [v['version'] for v in versions] == [1, 2]
    assert versions[0]['fields']['reason'] == '家庭事务'
    assert versions[1]['fields']['reason'] == '调整后的原因'
    details = (await client.get(f'/api/agent/threads/{tid}', headers=emp_headers)).json()['data']
    assert [d['action'] for d in details['approval_decisions']] == ['reject']
    assert details['approval_decisions'][0]['application_version'] == 1


@pytest.mark.asyncio
async def test_builtin_edit_rechecks_and_replay_does_not_add_versions(client, emp_headers):
    application = await make_submitted(client, emp_headers)
    aid = application['application_id']
    payload = {'action': 'edit', 'comment': '补充说明', 'edited_data': {'reason': '审批补充'},
               'idempotency_key': 'edit-v1'}
    mgr = {'Authorization': 'Bearer mock:u_mgr_001'}
    edited = await client.post(f'/api/leaves/{aid}/decision', json=payload, headers=mgr)
    assert edited.status_code == 200
    assert edited.json()['data']['status'] == 'WAITING_HUMAN'
    replay = await client.post(f'/api/leaves/{aid}/decision', json=payload, headers=mgr)
    assert replay.status_code == 200
    versions = (await client.get(f'/api/leaves/{aid}/versions', headers=emp_headers)).json()['data']
    assert len(versions) == 2
    assert versions[0]['fields']['reason'] == '家庭事务'
    assert versions[1]['fields']['reason'] == '审批补充'
    assert versions[1]['precheck']['passed'] is True
    failed_edit = await client.post(f'/api/leaves/{aid}/decision', json={
        'action': 'edit', 'comment': '病假必须重新补材料',
        'edited_data': {'leave_type': 'sick'}, 'idempotency_key': 'edit-v2',
    }, headers=mgr)
    assert failed_edit.status_code == 200
    assert failed_edit.json()['data']['status'] == 'NEEDS_FIX'
    forbidden = await client.post(f'/api/leaves/{aid}/decision', json={
        'action': 'approve', 'idempotency_key': 'approve-invalid'}, headers=mgr)
    assert forbidden.status_code == 409
    details = (await client.get('/api/agent/threads/' + application['thread_id'], headers=emp_headers)).json()['data']
    assert details['active_approval_node'] is None


@pytest.mark.asyncio
async def test_early_decision_replay_cannot_regress_approved_status(client, emp_headers):
    application = await make_submitted(client, emp_headers)
    aid = application['application_id']
    first = {'action': 'approve', 'idempotency_key': 'first'}
    mgr1 = {'Authorization': 'Bearer mock:u_mgr_001'}
    await client.post(f'/api/leaves/{aid}/decision', json=first, headers=mgr1)
    await client.post(f'/api/leaves/{aid}/decision', json={
        'action': 'approve', 'idempotency_key': 'second'},
        headers={'Authorization': 'Bearer mock:u_mgr_002'})
    replay = await client.post(f'/api/leaves/{aid}/decision', json=first, headers=mgr1)
    assert replay.status_code == 200
    assert replay.json()['data']['status'] == 'APPROVED'
    owned = await client.get(f'/api/leaves/{aid}', headers=emp_headers)
    assert owned.json()['data']['status'] == 'APPROVED'


@pytest.mark.asyncio
async def test_leave_list_owner_filter_pagination_and_restored_precheck(client, emp_headers):
    application = await make_submitted(client, emp_headers)
    listed = await client.get('/api/leaves?status=SUBMITTED&page_size=1', headers=emp_headers)
    assert listed.status_code == 200
    assert listed.json()['data']['total'] == 1
    assert listed.json()['data']['items'][0]['application_id'] == application['application_id']
    unrelated = await client.get('/api/leaves', headers={'Authorization': 'Bearer mock:u_cs_001'})
    assert unrelated.json()['data']['total'] == 0
    restored = await client.get('/api/leaves/' + application['application_id'], headers=emp_headers)
    assert restored.json()['data']['precheck']['passed'] is True


@pytest.mark.asyncio
async def test_builtin_leave_balance_is_read_from_provider_and_can_fail_precheck(client, emp_headers):
    created = await client.post('/api/leaves', json={
        'leave_type': 'personal', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-22T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    assert created.status_code == 200
    aid = created.json()['data']['application_id']
    submitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    data = submitted.json()['data']
    assert submitted.status_code == 200
    assert data['status'] == 'NEEDS_FIX'
    balance = next(item for item in data['precheck']['items'] if item['item'] == 'balance')
    assert balance['result'] == 'fail'
    assert '余额不足' in balance['reason']


@pytest.mark.asyncio
async def test_builtin_leave_conflict_reads_existing_applications(client, emp_headers):
    first = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-21T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    first_id = first.json()['data']['application_id']
    assert (await client.post(f'/api/leaves/{first_id}/submit', headers=emp_headers)).json()['data']['status'] == 'SUBMITTED'

    second = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-21T09:00:00+08:00',
        'end_at': '2026-10-22T18:00:00+08:00', 'reason': '重复安排',
    }, headers=emp_headers)
    second_id = second.json()['data']['application_id']
    submitted = await client.post(f'/api/leaves/{second_id}/submit', headers=emp_headers)
    data = submitted.json()['data']
    assert submitted.status_code == 200
    assert data['status'] == 'NEEDS_FIX'
    conflict = next(item for item in data['precheck']['items'] if item['item'] == 'conflict')
    assert conflict['result'] == 'fail'
    assert '冲突' in conflict['reason']


@pytest.mark.asyncio
async def test_builtin_leave_balance_dependency_failure_pauses_without_approval(client, emp_headers, monkeypatch):
    from app.adapters.factory import get_adapter

    def unavailable(*args):
        raise TimeoutError('余额服务超时')

    original_balance = get_adapter().get_leave_balance
    monkeypatch.setattr(get_adapter(), 'get_leave_balance', unavailable)
    created = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-20T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    aid = created.json()['data']['application_id']
    submitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    data = submitted.json()['data']
    assert submitted.status_code == 200
    assert data['status'] == 'PAUSED'
    assert data['precheck']['passed'] is False
    assert data['precheck']['status'] == 'PAUSED'
    assert data['thread_id'] is None
    assert data['precheck']['error']['code'] == '50201'
    assert 'trace_id' in data['precheck']['error']
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalInstance))).all() == []
    monkeypatch.setattr(get_adapter(), 'get_leave_balance', original_balance)
    restored = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert restored.json()['data']['status'] == 'SUBMITTED'
    assert restored.json()['data']['version'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('end_at', ['2026-10-20T09:00:00+08:00', '2026-10-19T18:00:00+08:00'])
async def test_builtin_invalid_interval_is_not_approved(client, emp_headers, end_at):
    created = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': end_at, 'reason': '家庭事务',
    }, headers=emp_headers)
    aid = created.json()['data']['application_id']
    data = (await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)).json()['data']
    assert data['status'] == 'NEEDS_FIX'
    assert next(item for item in data['precheck']['items'] if item['item'] == 'conflict')['result'] == 'fail'
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalInstance))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('other_status', ['SUBMITTED', 'APPROVED', 'DRAFT', 'REJECTED'])
async def test_conflict_status_and_boundary_are_respected(client, emp_headers, other_status):
    async with async_session_factory() as db:
        db.add(LeaveApplication(tenant_id='t_001', user_id='u_emp_001', business_id='LA-EXISTING',
                               status=other_status, current_version=0, latest_fields={
                                   'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
                                   'end_at': '2026-10-20T18:00:00+08:00'}))
        await db.commit()
    for start_at, expected in [('2026-10-20T10:00:00+08:00',
                               'NEEDS_FIX' if other_status in {'SUBMITTED', 'APPROVED'} else 'SUBMITTED'),
                              ('2026-10-20T18:00:00+08:00', 'SUBMITTED')]:
        created = await client.post('/api/leaves', json={
            'leave_type': 'annual', 'start_at': start_at,
            'end_at': '2026-10-20T19:00:00+08:00' if '10:00' in start_at else '2026-10-20T20:00:00+08:00',
            'reason': '家庭事务',
        }, headers=emp_headers)
        aid = created.json()['data']['application_id']
        data = (await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)).json()['data']
        assert data['status'] == expected
        # Leave only the seeded record active for the next assertion.
        async with async_session_factory() as db:
            row = await db.get(LeaveApplication, aid)
            row.status = 'REJECTED'
            await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize('tenant_id,user_id', [('t_other', 'u_emp_001'), ('t_001', 'u_cs_001')])
async def test_conflict_excludes_other_owners_and_tenants(client, emp_headers, tenant_id, user_id):
    async with async_session_factory() as db:
        db.add(LeaveApplication(tenant_id=tenant_id, user_id=user_id, business_id='LA-PRIVATE',
                               status='APPROVED', current_version=0, latest_fields={
                                   'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
                                   'end_at': '2026-10-20T18:00:00+08:00'}))
        await db.commit()
    data = await make_submitted(client, emp_headers)
    assert data['status'] == 'SUBMITTED'
    assert 'LA-PRIVATE' not in str(data['precheck'])


@pytest.mark.asyncio
async def test_mixed_timezone_interval_is_checked_consistently(client, emp_headers):
    created = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00',
        'end_at': '2026-10-20T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    aid = created.json()['data']['application_id']
    data = (await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)).json()['data']
    assert data['status'] == 'SUBMITTED'


@pytest.mark.asyncio
async def test_corrupt_active_materials_pause_conflict_check(client, emp_headers):
    async with async_session_factory() as db:
        db.add(LeaveApplication(tenant_id='t_001', user_id='u_emp_001', business_id='LA-CORRUPT',
                               status='APPROVED', current_version=0, latest_fields={'leave_type': 'annual'}))
        await db.commit()
    data = await make_submitted(client, emp_headers)
    assert data['status'] == 'PAUSED'
    assert data['precheck']['error']['dependency'] == 'conflict'


@pytest.mark.asyncio
async def test_pending_and_approved_applications_consume_available_balance(client, emp_headers):
    first = await client.post('/api/leaves', json={
        'leave_type': 'personal', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-21T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    aid = first.json()['data']['application_id']
    assert (await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)).json()['data']['status'] == 'SUBMITTED'
    for other_status in ['SUBMITTED', 'APPROVED']:
        async with async_session_factory() as db:
            row = await db.get(LeaveApplication, aid)
            row.status = other_status
            await db.commit()
        second = await client.post('/api/leaves', json={
            'leave_type': 'personal', 'start_at': '2026-10-24T09:00:00+08:00',
            'end_at': '2026-10-24T18:00:00+08:00', 'reason': '家庭事务',
        }, headers=emp_headers)
        second_id = second.json()['data']['application_id']
        data = (await client.post(f'/api/leaves/{second_id}/submit', headers=emp_headers)).json()['data']
        assert data['status'] == 'NEEDS_FIX'
        assert next(item for item in data['precheck']['items'] if item['item'] == 'balance')['result'] == 'fail'


@pytest.mark.asyncio
async def test_concurrent_overlapping_submissions_cannot_both_pass(client, emp_headers):
    import asyncio
    ids = []
    for _ in range(2):
        created = await client.post('/api/leaves', json={
            'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
            'end_at': '2026-10-20T18:00:00+08:00', 'reason': '家庭事务',
        }, headers=emp_headers)
        ids.append(created.json()['data']['application_id'])
    responses = await asyncio.gather(*(client.post(f'/api/leaves/{aid}/submit', headers=emp_headers) for aid in ids))
    assert sorted(response.json()['data']['status'] for response in responses) == ['NEEDS_FIX', 'SUBMITTED']


@pytest.mark.asyncio
async def test_approval_rechecks_balance_drift_before_advancing(client, emp_headers, monkeypatch):
    from app.adapters.factory import get_adapter
    from app.adapters.oa_adapter import Balance
    from app.models.approval_decision import ApprovalDecision
    application = await make_submitted(client, emp_headers)
    aid = application['application_id']
    monkeypatch.setattr(get_adapter(), 'get_leave_balance',
                        lambda *args: Balance(leave_type='annual', total=10, used=10, remaining=0))
    decided = await client.post(f'/api/leaves/{aid}/decision', json={
        'action': 'approve', 'idempotency_key': 'balance-drift'},
        headers={'Authorization': 'Bearer mock:u_mgr_001'})
    assert decided.status_code == 200
    assert decided.json()['data']['status'] == 'NEEDS_FIX'
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalDecision))).all() == []
        instance = (await db.scalars(select(ApprovalInstance))).one()
        assert instance.status == 'NEEDS_FIX'
    owned = (await client.get(f'/api/leaves/{aid}', headers=emp_headers)).json()['data']
    assert owned['status'] == 'NEEDS_FIX'
    assert owned['precheck']['passed'] is False


@pytest.mark.asyncio
async def test_approval_edit_dependency_pause_can_resume_from_employee_form(client, emp_headers, monkeypatch):
    from app.adapters.factory import get_adapter
    application = await make_submitted(client, emp_headers)
    aid = application['application_id']
    original_balance = get_adapter().get_leave_balance
    def unavailable(*args):
        raise TimeoutError('sensitive provider endpoint token=secret')
    monkeypatch.setattr(get_adapter(), 'get_leave_balance', unavailable)
    payload = {'action': 'edit', 'comment': '补充说明', 'edited_data': {'reason': '修改后的说明'},
               'idempotency_key': 'paused-edit'}
    manager = {'Authorization': 'Bearer mock:u_mgr_001'}
    decided = await client.post(f'/api/leaves/{aid}/decision', json=payload, headers=manager)
    assert decided.status_code == 200
    assert decided.json()['data']['status'] == 'PAUSED'
    owned = (await client.get(f'/api/leaves/{aid}', headers=emp_headers)).json()['data']
    assert owned['fields']['reason'] == '修改后的说明'
    assert owned['precheck']['status'] == 'PAUSED'
    assert 'secret' not in str(owned)
    blocked = await client.post(f'/api/leaves/{aid}/decision', json={
        'action': 'approve', 'idempotency_key': 'blocked'}, headers=manager)
    assert blocked.status_code == 409
    replay = await client.post(f'/api/leaves/{aid}/decision', json=payload, headers=manager)
    assert replay.status_code == 200
    assert replay.json()['data']['status'] == 'PAUSED'
    monkeypatch.setattr(get_adapter(), 'get_leave_balance', original_balance)
    restored = (await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)).json()['data']
    assert restored['status'] == 'SUBMITTED'
    assert restored['thread_id'] == application['thread_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['total', 'used', 'remaining'])
async def test_nonfinite_balance_is_unknown_and_pauses(client, emp_headers, monkeypatch, field):
    from app.adapters.factory import get_adapter
    from app.adapters.oa_adapter import Balance
    values = {'total': 10, 'used': 3, 'remaining': 7}
    values[field] = float('inf')
    monkeypatch.setattr(get_adapter(), 'get_leave_balance',
                        lambda *args: Balance(leave_type='annual', **values))
    data = await make_submitted(client, emp_headers)
    assert data['status'] == 'PAUSED'
    assert data['precheck']['error']['dependency'] == 'balance'


@pytest.mark.asyncio
async def test_unrelated_paused_approval_cannot_be_edited_or_resubmitted(client, emp_headers):
    application = await make_submitted(client, emp_headers)
    aid = application['application_id']
    async with async_session_factory() as db:
        row = await db.get(LeaveApplication, aid)
        row.status = 'PAUSED'
        instance = (await db.scalars(select(ApprovalInstance))).one()
        instance.status = 'PENDING_WRITE'
        await db.commit()
    patched = await client.patch(f'/api/leaves/{aid}', json={'reason': '覆盖未知外部写入'}, headers=emp_headers)
    assert patched.status_code == 409
    submitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert submitted.status_code == 409


@pytest.mark.asyncio
async def test_builtin_route_dependency_pause_is_recoverable_without_creating_approval(client, emp_headers, monkeypatch):
    from app.adapters.factory import get_adapter
    original_route = get_adapter().get_approval_route
    def unavailable(*args):
        raise TimeoutError('组织路由超时')
    monkeypatch.setattr(get_adapter(), 'get_approval_route', unavailable)
    created = await client.post('/api/leaves', json={
        'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-20T18:00:00+08:00', 'reason': '家庭事务',
    }, headers=emp_headers)
    aid = created.json()['data']['application_id']
    result = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert result.status_code == 200
    assert result.json()['data']['status'] == 'PAUSED'
    assert result.json()['data']['precheck']['error']['dependency'] == 'route'
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalInstance))).all() == []
    monkeypatch.setattr(get_adapter(), 'get_approval_route', original_route)
    restored = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert restored.json()['data']['status'] == 'SUBMITTED'
