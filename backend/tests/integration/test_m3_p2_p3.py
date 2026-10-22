"""P2/P3 formal paths retain owner scope when source or policy changes."""
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.context import CurrentUser
from app.db.session import async_session_factory, engine
from app.services import oa_scope_service
from tests.integration.test_m3_document_sources import formal_documents as formal_scope
from tests.oa_support import oa_db, seed


@pytest.mark.asyncio
async def test_formal_policy_disable_is_scene_local_and_audit_export_source_is_scoped(formal_scope):
    async with formal_scope() as session:
        actor = await seed(session, resources=['audit', 'report'])
        await oa_scope_service.upsert_formal_policy(session, actor=actor, scene="report", scope_type="tenant",
            scope_value=None, enabled=False, thresholds={}, rule_version="v1")
        await oa_scope_service.upsert_formal_policy(session, actor=actor, scene="contract", scope_type="tenant",
            scope_value=None, enabled=True, thresholds={}, rule_version="v1")
        await oa_scope_service.record_audit(session, actor=actor, resource="report", action="paused")
        await session.commit()
        report = await oa_scope_service.formal_policy(session, actor=actor, scene="report")
        contract = await oa_scope_service.formal_policy(session, actor=actor, scene="contract")
        assert report.enabled is False
        assert contract.enabled is True
        assert len(await oa_scope_service.visible_audits(session, actor=actor, resource="report")) == 1

