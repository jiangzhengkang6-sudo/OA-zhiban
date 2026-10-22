"""Formal M3 tenant, department and source scope checks."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.context import CurrentUser
from app.db.session import async_session_factory, engine
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.oa_ai_scope import OABusinessAudit
from app.services import oa_scope_service
from tests.integration.test_m3_document_sources import formal_documents as formal_scope
from tests.oa_support import oa_db, seed


@pytest.mark.asyncio
async def test_formal_source_policy_and_audit_are_tenant_and_department_scoped(formal_scope):
    async with formal_scope() as session:
        owner = await seed(session, resources=['audit'])
        peer = await seed(session, tenant=owner.tenant_id, resources=['audit'])
        source = KnowledgeSource(tenant_id=owner.tenant_id, name="部门制度", owner_id=owner.user_id)
        foreign = KnowledgeSource(tenant_id='foreign-' + owner.tenant_id, name="外部制度", owner_id="foreign")
        session.add_all([source, foreign])
        await session.flush()
        version = KnowledgeVersion(source_id=source.id, version=1, status="published", parse_status="READY",
                                   permission_tags=[], owner_id=owner.user_id)
        session.add(version)
        await session.flush()
        await oa_scope_service.create_binding(session, actor=owner, source_id=source.id, owner_id=owner.user_id,
            department_id=owner.depts[0], access_scope="department")
        policy, published = await oa_scope_service.upsert_formal_policy(session, actor=owner, scene="document",
            scope_type="department", scope_value=owner.depts[0], enabled=True,
            thresholds={"intent_confidence": 0.8}, rule_version="v2")
        await oa_scope_service.record_audit(session, actor=owner, resource="document", action="generated",
            object_type="document", object_id="doc-a", source_id=str(source.id))
        await session.commit()
        assert await oa_scope_service.source_allowed(session, owner, source.id, version_id=version.id)
        assert not await oa_scope_service.source_allowed(session, peer, source.id, version_id=version.id)
        assert not await oa_scope_service.source_allowed(session, owner, foreign.id)
        resolved = await oa_scope_service.formal_policy(session, actor=owner, scene="document")
        assert resolved is not None and resolved.version_number == published.version
        assert resolved.thresholds["intent_confidence"] == 0.8
        rows = await oa_scope_service.visible_audits(session, actor=peer)
        assert rows == []

