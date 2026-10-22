from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_ticket import FormalTicketProposal,FormalTicketCommand,TicketHandleCommand,TicketFeedbackCommand,TicketRuleSave
from ...services import oa_ticket_service as service

router=APIRouter(prefix='/oa/tickets',tags=['正式工单'])


@router.get('')
async def items(handling: bool=False,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_tickets(db,actor,handling=handling))


@router.post('/prepare')
async def prepare(payload: FormalTicketProposal,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.prepare(db,actor,payload)
    await db.commit()
    return ok(result)


@router.post('')
async def create(payload: FormalTicketCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    proposal=FormalTicketProposal.model_validate(payload.model_dump(exclude={'confirmation_id'}))
    result=await service.create_or_merge(db,actor,proposal,confirmation_id=payload.confirmation_id)
    await db.commit()
    return ok(result.response())


@router.get('/results/{operation_id}')
async def result(operation_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.get_result(db,actor,operation_id))


@router.get('/rules')
async def rules(department_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_rules(db,actor,department_id))


@router.post('/rules')
async def save_rule(payload: TicketRuleSave,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.save_rule(db,actor,payload)
    await db.commit()
    return ok(result.response())


@router.get('/{ticket_id}')
async def detail(ticket_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.detail(db,actor,ticket_id))


@router.post('/{ticket_id}/handle')
async def handle(ticket_id: str,payload: TicketHandleCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.handle(db,actor,ticket_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{ticket_id}/feedback')
async def feedback(ticket_id: str,payload: TicketFeedbackCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.feedback(db,actor,ticket_id,payload)
    await db.commit()
    return ok(result.response())
