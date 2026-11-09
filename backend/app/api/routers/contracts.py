from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.contract import ContractInput, ContractCommand
from ...services import contract_service as service
from ...services.contract_parser import MAX_BYTES
from ...core.errors import AppException
from ...core.enums import ErrorCode
from ..deps import get_current_user

router = APIRouter(prefix='/contracts',tags=['contracts'])


@router.post('')
async def create(payload: ContractInput,session: AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    result = await service.create_contract(session,user,payload)
    await session.commit()
    return ok(result)


@router.post('/uploads')
async def upload(title: str=Form(...,min_length=1,max_length=255),reviewer_id: str=Form(...,min_length=1,max_length=64),
    idempotency_key: str=Form(...,min_length=1,max_length=128),file: UploadFile=File(...),
    session: AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    await service._identity(session, user)
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise AppException(ErrorCode.BAD_REQUEST,'文件超过5MiB',http_status=422)
    payload = ContractInput(title=title,reviewer_id=reviewer_id,text='uploaded',idempotency_key=idempotency_key)
    result = await service.create_contract(session,user,payload,upload=(file.filename or '',file.content_type or '',content))
    await session.commit()
    return ok(result)


@router.get('')
async def listing(page:int=1,page_size:int=20,session:AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    return ok(await service.list_contracts(session,user,page,page_size))


@router.get('/reviewers')
async def reviewers(session:AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    return ok(await service.reviewer_options(session,user))


@router.get('/{contract_id}')
async def detail(contract_id:str,session:AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    return ok(await service.get_contract(session,user,contract_id))


@router.get('/{contract_id}/versions')
async def versions(contract_id:str,session:AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    return ok(await service.list_versions(session,user,contract_id))


@router.get('/{contract_id}/sources/{source_id}')
async def source(contract_id:str,source_id:str,session:AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    return ok(await service.source_detail(session,user,contract_id,source_id))


@router.post('/{contract_id}/commands')
async def command(contract_id:str,payload:ContractCommand,session:AsyncSession=Depends(get_db),user=Depends(get_current_user)):
    result = await service.command_contract(session,user,contract_id,payload)
    await session.commit()
    return ok(result)
