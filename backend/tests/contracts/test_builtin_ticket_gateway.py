"""Durable ticket recovery through the async gateway, without a checkpoint."""
import pytest
from sqlalchemy import delete, func, select

from app.adapters.builtin_gateway import BuiltinGateway
from app.adapters.gateway import BridgeContext
from app.core.errors import AppException
from app.models.identity import OAPermission, OARolePermission, OAUserRole
from app.models.oa_ticket import OATicket
from app.models.oa_workflow import OAWorkflowEvent
from app.services import oa_ticket_service as tickets
from tests.api.test_oa_ticket import setup, proposal
from tests.oa_support import oa_db


async def test_gateway_ticket_recovers_original_result_and_rechecks_authority(oa_db):
    async with oa_db() as db:
        _, actor = await setup(db)
        values = proposal('bridge-ticket')
        confirmation = await tickets.prepare(db, actor, values)
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db, trace_id='ticket-trace',
            confirmation_id=confirmation['confirmation_id']))
        result = await gateway.create_or_merge_ticket(values)
        await db.commit()
    async with oa_db() as db:
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db,
            confirmation_id=confirmation['confirmation_id']))
        assert await gateway.get_ticket_result('bridge-ticket') == result
        assert await gateway.get_ticket_result('missing') is None
        assert (await gateway.get_ticket_status(result['id']))['id'] == result['id']
        assert await gateway.create_or_merge_ticket(values) == result
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(OATicket).where(OATicket.tenant_id == actor.tenant_id)) == 1
        event = await db.scalar(select(OAWorkflowEvent).where(
            OAWorkflowEvent.tenant_id == actor.tenant_id, OAWorkflowEvent.action == 'ticket.create_or_merge'))
        assert event.trace_id == 'ticket-trace'
        await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id == actor.tenant_id,
            OARolePermission.role_id.in_(select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id)),
            OARolePermission.permission_id.in_(select(OAPermission.id).where(OAPermission.resource == 'ticket'))))
        await db.commit()
        for method, value in [('get_ticket_result', 'bridge-ticket'), ('get_ticket_status', result['id']),
                              ('create_or_merge_ticket', values)]:
            with pytest.raises(AppException) as error:
                await getattr(gateway, method)(value)
            assert error.value.http_status == 403
