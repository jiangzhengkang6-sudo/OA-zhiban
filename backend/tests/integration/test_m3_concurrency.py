import asyncio
import pytest
from sqlalchemy import select,func
from app.core.errors import AppException
from tests.oa_support import oa_db,seed
from tests.api.test_oa_ticket import setup,create,proposal


async def test_competing_claims_have_one_winner(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketHandleCommand
    async with oa_db() as db:
        first,owner=await setup(db)
        second=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=['ticket_handle'])
        await db.commit()
        ticket,_,_=await create(db,owner)
    async def claim(actor):
        async with oa_db() as db:
            try:
                result=await service.handle(db,actor,ticket['id'],TicketHandleCommand(operation_id=actor.user_id,expected_revision=1,action='claim'))
                await db.commit()
                return result.result['assignee_id']
            except AppException:
                await db.rollback()
                return None
    results=await asyncio.gather(claim(first),claim(second))
    assert sum(value is not None for value in results)==1
    async with oa_db() as db:
        assert (await service.detail(db,owner,ticket['id']))['assignee_id'] in {first.user_id,second.user_id}


async def test_confirmation_parallel_consumption_and_key_change(oa_db):
    from app.services import oa_ticket_service as service
    from app.models.oa_ticket import OATicket
    async with oa_db() as db:
        _,owner=await setup(db)
        command=proposal()
        confirmation=await service.prepare(db,owner,command)
        await db.commit()
    async def run():
        async with oa_db() as db:
            result=await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])
            await db.commit()
            return result.replayed
    assert sorted(await asyncio.gather(run(),run()))==[False,True]
    async with oa_db() as db:
        with pytest.raises(AppException): await service.create_or_merge(db,owner,command.model_copy(update={'operation_id':'other-key'}),confirmation_id=confirmation['confirmation_id'])
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(OATicket).where(OATicket.tenant_id==owner.tenant_id))==1
