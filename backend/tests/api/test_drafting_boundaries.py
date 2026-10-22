"""Document and mail recovery, policy, evidence and tenant boundaries."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.adapters.factory import get_adapter
from app.core.config import get_settings
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.agent_policy import AgentPolicy
from app.models.audit_event import AuditEvent
from app.models.degradation_state import DegradationState
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.knowledge_chunk import KnowledgeChunk
from app.services import document_generator, document_service, email_generator, email_service

EMP = {"Authorization": "Bearer mock:u_emp_001"}
ADMIN = {"Authorization": "Bearer mock:u_admin_001"}
SCENES = [("document", "documents", "generate", document_generator, document_service),
          ("email", "emails", "analyze", email_generator, email_service)]


@pytest.fixture
async def drafting_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE agent_thread, document_record, email_record, idempotency_record, "
                                "audit_event, agent_policy, policy_version, degradation_state, knowledge_source, "
                                "knowledge_chunk CASCADE"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def input_for(scene, key="create", **overrides):
    payload = dict(subject="项目验收", idempotency_key=key)
    if scene == "document":
        payload.update(template_id="notice", recipient="项目组", deadline="周五", basis="项目计划",
                       key_points="提交验收材料", distribution="内部")
    else:
        payload.update(sender="a@test.com", recipients=["b@test.com"], body="请提交验收材料")
    return {**payload, **overrides}


async def create(client, scene, path, **overrides):
    response = await client.post(f"/api/{path}", headers=EMP, json=input_for(scene, **overrides))
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scene,path,action,generator,service", SCENES)
async def test_generation_failure_replay_retry_and_regeneration_keep_versions(
        drafting_client, monkeypatch, scene, path, action, generator, service):
    original = generator.generate
    attempts = []

    async def fail(*args):
        attempts.append(True)
        raise TimeoutError("SECRET-MODEL-INPUT")

    created = await create(drafting_client, scene, path)
    url = f"/api/{path}/{created[scene + '_id']}"
    monkeypatch.setattr(generator, "generate", fail)
    command = {"idempotency_key": "generate", "expected_version": None}
    first = (await drafting_client.post(url + "/" + action, headers=EMP, json=command)).json()["data"]
    assert first["status"] == "PAUSED" and first["version"] is None
    assert first["error"]["trace_id"] and "SECRET" not in str(first)
    assert (await drafting_client.post(url + "/" + action, headers=EMP, json=command)).json()["data"] == first
    retry = {"idempotency_key": "retry", "expected_version": None}
    paused = (await drafting_client.post(url + "/retry", headers=EMP, json=retry)).json()["data"]
    assert paused["status"] == "PAUSED"
    assert (await drafting_client.post(url + "/retry", headers=EMP, json=retry)).json()["data"] == paused
    assert len(attempts) == 2
    monkeypatch.setattr(generator, "generate", original)
    recovered = await drafting_client.post(url + "/retry", headers=EMP, json={**retry, "idempotency_key": "recover"})
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["version"] == 1
    monkeypatch.setattr(generator, "generate", fail)
    failed_regen = await drafting_client.post(url + "/decisions", headers=EMP,
        json={"action": "regenerate", "expected_version": 1, "idempotency_key": "regen-fail"})
    assert failed_regen.json()["data"]["status"] == "PAUSED"
    assert failed_regen.json()["data"]["version"] == 1
    monkeypatch.setattr(generator, "generate", original)
    recovered = await drafting_client.post(url + "/retry", headers=EMP,
                                          json={"expected_version": 1, "idempotency_key": "recover-2"})
    assert recovered.json()["data"]["version"] == 2
    assert len((await drafting_client.get(url + "/versions", headers=EMP)).json()["data"]) == 2
    async with async_session_factory() as db:
        events = (await db.scalars(select(AuditEvent).where(AuditEvent.business_id == created[scene + '_id']))).all()
        assert "SECRET" not in str([(e.input_summary, e.output_summary) for e in events])


@pytest.mark.asyncio
@pytest.mark.parametrize("scene,path,action,generator,service", SCENES)
async def test_persistence_failure_rolls_back_instead_of_becoming_model_pause(
        drafting_client, monkeypatch, scene, path, action, generator, service):
    created = await create(drafting_client, scene, path)
    url = f"/api/{path}/{created[scene + '_id']}"
    persist = service._persist

    async def crash(*args, **kwargs):
        raise RuntimeError("business persistence failure")

    monkeypatch.setattr(service, "_persist", crash)
    command = {"idempotency_key": "generation"}
    with pytest.raises(RuntimeError, match="business persistence"):
        await drafting_client.post(url + "/" + action, headers=EMP, json=command)
    monkeypatch.setattr(service, "_persist", persist)
    assert (await drafting_client.get(url, headers=EMP)).json()["data"]["status"] == "CREATED"
    recovered = await drafting_client.post(url + "/" + action, headers=EMP, json=command)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["version"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scene,path,action,generator,service", SCENES)
async def test_role_revocation_tenant_change_and_policy_degradation(
        drafting_client, monkeypatch, scene, path, action, generator, service):
    created = await create(drafting_client, scene, path)
    url = f"/api/{path}/{created[scene + '_id']}"
    command = {"idempotency_key": "generate"}
    draft = (await drafting_client.post(url + "/" + action, headers=EMP, json=command)).json()["data"]["draft"]
    users = get_adapter()._state["users"]
    original = users["u_emp_001"]
    monkeypatch.setitem(users, "u_emp_001", {**original, "roles": []})
    task_list = await drafting_client.get(f"/api/tasks?scene={scene}", headers=EMP)
    assert task_list.status_code == 200
    assert task_list.json()["data"]["items"] == []
    for suffix in ("", "/versions"):
        assert (await drafting_client.get(url + suffix, headers=EMP)).status_code == 403
    assert (await drafting_client.post(url + "/" + action, headers=EMP, json=command)).status_code == 403
    monkeypatch.setitem(users, "u_emp_001", {**original, "tenant_id": "other"})
    assert (await drafting_client.get(url, headers=EMP)).status_code in {403, 404}
    monkeypatch.setitem(users, "u_emp_001", original)
    async with async_session_factory() as db:
        db.add(AgentPolicy(scene=scene, scope_type="global", enabled=False, rule_version="v1"))
        await db.commit()
    assert (await drafting_client.post(f"/api/{path}", headers=EMP, json=input_for(scene, "off"))).status_code == 503
    assert (await drafting_client.post(url + "/" + action, headers=EMP, json=command)).status_code == 200
    async with async_session_factory() as db:
        policy = await db.scalar(select(AgentPolicy).where(AgentPolicy.scene == scene))
        policy.enabled = True
        db.add(DegradationState(scene=scene, scope_type="tenant", scope_value="t_001", enabled=True,
               new_task_action="fallback", inflight_action="pause", reason="维护", created_by="u_admin_001"))
        await db.commit()
    assert (await drafting_client.patch(url + "/draft", headers=EMP,
        json={"draft": draft, "expected_version": 1, "idempotency_key": "degraded-edit"})).status_code == 503
    assert (await drafting_client.get(url, headers=EMP)).json()["data"]["version"] == 1
    admin_task = await drafting_client.get(f"/api/tasks/{created['thread_id']}", headers=ADMIN)
    assert admin_task.status_code == 200
    assert admin_task.json()["data"]["available_actions"] == []
    assert (await drafting_client.post(f"/api/tasks/{created['thread_id']}/retry", headers=EMP)).status_code == 422


@pytest.mark.asyncio
async def test_document_knowledge_filters_and_revocation_cover_replays(drafting_client, monkeypatch):
    vector = [1.0] + [0.0] * (get_settings().embedding_dim - 1)
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        for name, tenant, tags, status, parse, effective, expires in [
            ("allowed", "t_001", ["d_rd"], "published", "READY", None, None),
            ("other-tenant", "other", [], "published", "READY", None, None),
            ("other-dept", "t_001", ["d_hr"], "published", "READY", None, None),
            ("draft", "t_001", [], "draft", "READY", None, None),
            ("unparsed", "t_001", [], "published", "PENDING", None, None),
            ("expired", "t_001", [], "published", "READY", None, now - timedelta(days=1)),
            ("future", "t_001", [], "published", "READY", now + timedelta(days=1), None),
        ]:
            source = KnowledgeSource(tenant_id=tenant, name=name)
            db.add(source); await db.flush()
            version = KnowledgeVersion(source_id=source.id, version=1, status=status, permission_tags=tags,
                                       parse_status=parse, effective_at=effective, expire_at=expires)
            db.add(version); await db.flush()
            db.add(KnowledgeChunk(document_id=uuid4(), version_id=version.id, chunk_index=0,
                                  content=name + " 验收规范", embedding=vector, source_location="page:1"))
            if name == "allowed":
                allowed_id = version.id
        await db.commit()
    created = await create(drafting_client, "document", "documents", use_knowledge=True)
    assert [s["title"] for s in created["sources"] if s["kind"] == "knowledge"] == ["allowed"]
    url = f"/api/documents/{created['document_id']}"
    command = {"idempotency_key": "generate"}
    original_generate = document_generator.generate
    users = get_adapter()._state["users"]
    original_user = users["u_emp_001"]

    async def revoke_during_generation(*args):
        result = await original_generate(*args)
        monkeypatch.setitem(users, "u_emp_001", {**original_user, "dept_id": "d_hr"})
        return result

    monkeypatch.setattr(document_generator, "generate", revoke_during_generation)
    denied = await drafting_client.post(url + "/generate", headers=EMP, json=command)
    assert denied.status_code == 403
    monkeypatch.setitem(users, "u_emp_001", original_user)
    monkeypatch.setattr(document_generator, "generate", original_generate)
    assert (await drafting_client.get(url, headers=EMP)).json()["data"]["status"] == "CREATED"
    assert (await drafting_client.post(url + "/generate", headers=EMP, json=command)).status_code == 200
    async def revoke_and_fail(*args):
        monkeypatch.setitem(users, "u_emp_001", {**original_user, "dept_id": "d_hr"})
        raise TimeoutError("revoked during failed regeneration")

    monkeypatch.setattr(document_generator, "generate", revoke_and_fail)
    failed_regen = await drafting_client.post(url + "/decisions", headers=EMP,
        json={"action": "regenerate", "expected_version": 1, "idempotency_key": "failed-revoked"})
    assert failed_regen.status_code == 403
    monkeypatch.setitem(users, "u_emp_001", original_user)
    monkeypatch.setattr(document_generator, "generate", original_generate)
    assert (await drafting_client.get(url, headers=EMP)).json()["data"]["status"] == "DRAFT_READY"
    async with async_session_factory() as db:
        version = await db.get(KnowledgeVersion, allowed_id)
        version.permission_tags = ["d_hr"]
        await db.commit()
    assert (await drafting_client.get(url, headers=EMP)).status_code == 403
    assert (await drafting_client.get(url + "/versions", headers=EMP)).status_code == 403
    assert (await drafting_client.post(url + "/generate", headers=EMP, json=command)).status_code == 403
    assert (await drafting_client.post("/api/documents", headers=EMP,
        json=input_for("document", use_knowledge=True))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("scene,path,action,generator,service", SCENES)
async def test_invalid_model_evidence_pauses_without_a_revision(
        drafting_client, monkeypatch, scene, path, action, generator, service):
    original = generator.generate

    async def invalid(*args):
        result = await original(*args)
        return {**result, "source_refs": ["invented-ref"]}

    monkeypatch.setattr(generator, "generate", invalid)
    created = await create(drafting_client, scene, path)
    url = f"/api/{path}/{created[scene + '_id']}"
    response = await drafting_client.post(url + "/" + action, headers=EMP, json={"idempotency_key": "invalid"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "PAUSED"
    assert response.json()["data"]["version"] is None
    assert (await drafting_client.get(url + "/versions", headers=EMP)).json()["data"] == []


@pytest.mark.asyncio
async def test_email_secondary_confirmation_and_terminal_guards(drafting_client):
    created = await create(drafting_client, "email", "emails", external_contact=True)
    url = f"/api/emails/{created['email_id']}"
    draft = (await drafting_client.post(url + "/analyze", headers=EMP,
                                       json={"idempotency_key": "analyze"})).json()["data"]["draft"]
    decision = {"action": "confirm", "expected_version": 1, "idempotency_key": "confirm",
                "metadata_confirmed": True, "warnings_acknowledged": True}
    assert (await drafting_client.post(url + "/decisions", headers=EMP, json=decision)).status_code == 422
    response = await drafting_client.post(url + "/decisions", headers=EMP, json={**decision, "secondary_confirmed": True})
    assert response.status_code == 200, response.text
    assert (await drafting_client.patch(url + "/draft", headers=EMP,
        json={"draft": draft, "expected_version": 1, "idempotency_key": "terminal-edit"})).status_code == 422
    assert (await drafting_client.post(url + "/decisions", headers=EMP,
        json={"action": "regenerate", "expected_version": 1, "idempotency_key": "terminal-regen"})).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("scene,path,action,generator,service", SCENES)
async def test_role_revoked_during_failed_generation_denies_response(
        drafting_client, monkeypatch, scene, path, action, generator, service):
    created = await create(drafting_client, scene, path)
    url = f"/api/{path}/{created[scene + '_id']}"
    users = get_adapter()._state["users"]
    original = users["u_emp_001"]

    async def revoke_and_fail(*args):
        monkeypatch.setitem(users, "u_emp_001", {**original, "roles": []})
        raise TimeoutError("model failure after role revocation")

    monkeypatch.setattr(generator, "generate", revoke_and_fail)
    denied = await drafting_client.post(url + "/" + action, headers=EMP,
                                       json={"idempotency_key": "midflight"})
    assert denied.status_code == 403
    monkeypatch.setitem(users, "u_emp_001", original)
    assert (await drafting_client.get(url, headers=EMP)).json()["data"]["status"] == "CREATED"
