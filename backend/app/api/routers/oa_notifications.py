from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_notification import ContactSave,NotificationRetry
from ...services import oa_notification_service as service

router=APIRouter(prefix='/oa/notifications',tags=['站内消息与通知'])


@router.get('')
async def items(db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_inbox(db,actor))


@router.get('/contacts/{user_id}')
async def contact(user_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.get_contact(db,actor,user_id))


@router.put('/contacts/{user_id}')
async def save_contact(user_id: str,payload: ContactSave,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.save_contact(db,actor,user_id,**payload.model_dump())
    await db.commit()
    return ok(result.response())


@router.get('/deliveries')
async def deliveries(db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_deliveries(db,actor))


@router.post('/deliveries/{delivery_id}/retry')
async def retry(delivery_id: str,payload: NotificationRetry,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.retry_unknown(db,actor,delivery_id,**payload.model_dump())
    await db.commit()
    return ok(result.response())


@router.post('/{notification_id}/read')
async def read(notification_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.mark_read(db,actor,notification_id)
    await db.commit()
    return ok(result)
