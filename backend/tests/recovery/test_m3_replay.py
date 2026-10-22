from sqlalchemy import select,func
from tests.oa_support import oa_db
from tests.api.test_oa_ticket import setup,create


async def test_committed_ticket_recovers_without_graph_checkpoint(oa_db):
    from app.services import oa_ticket_service as service
    from app.models.oa_ticket import OATicket
    from app.models.oa_bridge import OABridgeResult
    async with oa_db() as db:
        _,owner=await setup(db)
        original,command,confirmation=await create(db,owner)
    # A new session knows only the original operation key and trusted confirmation.
    async with oa_db() as db:
        assert await service.get_result(db,owner,'missing') is None
        assert (await service.get_result(db,owner,command.operation_id))['id']==original['id']
        replay=await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])
        await db.commit()
        assert replay.replayed
        assert await db.scalar(select(func.count()).select_from(OATicket).where(OATicket.tenant_id==owner.tenant_id))==1
        assert await db.scalar(select(func.count()).select_from(OABridgeResult).where(OABridgeResult.tenant_id==owner.tenant_id))==1
