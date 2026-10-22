import pytest
import inspect
from sqlalchemy import select
from tests.oa_support import oa_db


def test_async_protocol_declares_every_advertised_builtin_method():
    from app.adapters.gateway import OAGateway
    from app.adapters.builtin_gateway import BuiltinGateway, CORE_CAPABILITIES, AUXILIARY_CAPABILITIES
    for name in CORE_CAPABILITIES + AUXILIARY_CAPABILITIES:
        declared = getattr(OAGateway, name, None)
        assert declared is not None, name
        assert inspect.iscoroutinefunction(declared), name
        assert inspect.signature(declared).parameters.keys() == inspect.signature(getattr(BuiltinGateway, name)).parameters.keys()


async def test_builtin_gateway_exposes_capabilities_without_legacy_adapter(oa_db):
    from app.adapters.gateway import BridgeContext
    from app.adapters.builtin_gateway import BuiltinGateway
    from tests.oa_support import seed
    async with oa_db() as db:
        actor=await seed(db,resources=['leave','leave_balance','approval','ticket','notification'])
        context=BridgeContext(actor=actor,session=db,trace_id='trace-gateway')
        gateway=BuiltinGateway(context)
        result=await gateway.capabilities()
        assert result['provider']=='builtin'
        assert set(result['capabilities']) >= {'get_user_context','get_leave_balance','get_ticket_result','get_notification_result'}
        assert context.session is db and context.actor.user_id==actor.user_id


async def test_builtin_gateway_rejects_cross_tenant_identity(oa_db):
    from app.adapters.gateway import BridgeContext
    from app.adapters.builtin_gateway import BuiltinGateway
    from app.core.errors import AppException
    from tests.oa_support import seed
    async with oa_db() as db:
        actor=await seed(db,resources=['leave'])
        other=await seed(db,resources=['leave'])
        with pytest.raises(AppException):
            await BuiltinGateway(BridgeContext(actor=actor,session=db)).get_user_context(other.user_id)


async def test_current_identity_context_does_not_require_leave_permission(oa_db):
    from app.adapters.gateway import BridgeContext
    from app.adapters.builtin_gateway import BuiltinGateway
    from tests.oa_support import seed
    async with oa_db() as db:
        actor = await seed(db, resources=['ticket'], scope='self')
        await db.commit()
        context = await BuiltinGateway(BridgeContext(actor=actor, session=db)).get_user_context()
        assert context['user_id'] == actor.user_id
        assert context['tenant_id'] == actor.tenant_id


async def test_context_cannot_use_leave_scope_to_read_another_identity(oa_db):
    from app.adapters.gateway import BridgeContext
    from app.adapters.builtin_gateway import BuiltinGateway
    from app.core.errors import AppException
    from tests.oa_support import seed
    async with oa_db() as db:
        actor = await seed(db, resources=['leave'])
        peer = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['leave'])
        await db.commit()
        with pytest.raises(AppException) as error:
            await BuiltinGateway(BridgeContext(actor=actor, session=db)).get_user_context(peer.user_id)
        assert error.value.http_status == 403
