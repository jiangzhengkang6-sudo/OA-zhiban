import io
import pytest
from PIL import Image
from starlette.datastructures import UploadFile, Headers
from app.core.errors import AppException
from app.schemas.oa_leave import LeaveDraftCreate, LeaveDraftPatch, SubmitLeaveCommand
from tests.oa_support import oa_db, seed
from tests.api.test_oa_leave_lifecycle import setup_leave, fields


def image_upload():
    stream = io.BytesIO()
    Image.new('RGB',(2,2),'white').save(stream,format='PNG')
    stream.seek(0)
    return UploadFile(stream,filename='proof.png',headers=Headers({'content-type':'image/png'}))


async def test_private_attachment_reference_scan_and_integrity(oa_db,monkeypatch):
    from app.services import oa_leave_service as leaves, oa_attachment_service as service
    from app.providers import file_scanner
    async with oa_db() as db:
        admin,actor,workflow = await setup_leave(db)
        draft = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields()))
        await db.commit()
        item = await service.upload(db,actor,draft.result['id'],image_upload(),operation_id='upload',expected_revision=1)
        await db.commit()
        assert item.result['attachment']['scan_status']=='PENDING'
        detail = await leaves.detail(db,actor,draft.result['id'])
        assert detail['attachments']==[item.result['attachment']]
        with pytest.raises(AppException): await service.preflight(db,actor,draft.result['id'],[item.result['attachment']['id']])
        await db.rollback()
        async def clean(content): return 'CLEAN'
        monkeypatch.setattr(file_scanner,'scan_bytes',clean)
        rescanned = await service.rescan(db,actor,draft.result['id'],item.result['attachment']['id'],operation_id='rescan',expected_revision=2)
        await db.commit()
        prepared = await service.preflight(db,actor,draft.result['id'],[item.result['attachment']['id']])
        assert prepared[0]['sha256'] and rescanned.result['attachment']['scan_status']=='CLEAN'
        foreign = await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['leave'],scope='self')
        await db.commit()
        with pytest.raises(AppException): await service.download(db,foreign,draft.result['id'],item.result['attachment']['id'])
        await db.rollback()
        other = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='other',workflow_definition_id=workflow,fields=fields()))
        await db.commit()
        with pytest.raises(AppException): await service.preflight(db,actor,other.result['id'],[item.result['attachment']['id']])
        await db.rollback()
        from app.models.oa_leave import OALeaveAttachment
        row = await db.get(OALeaveAttachment,item.result['attachment']['id'])
        path = service.storage_path(row)
        path.write_bytes(b'tampered')
        with pytest.raises(AppException): await service.preflight(db,actor,draft.result['id'],[row.id])


@pytest.mark.parametrize('status',['ERROR','INFECTED','PENDING'])
async def test_unclean_attachment_blocks_submission(oa_db,monkeypatch,status):
    from app.services import oa_leave_service as leaves, oa_attachment_service as service
    from app.providers import file_scanner
    async def scan(content): return status
    monkeypatch.setattr(file_scanner,'scan_bytes',scan)
    async with oa_db() as db:
        _,actor,workflow = await setup_leave(db)
        draft = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields()))
        await db.commit()
        await service.upload(db,actor,draft.result['id'],image_upload(),operation_id='upload',expected_revision=1)
        await db.commit()
        with pytest.raises(AppException): await leaves.submit(db,actor,draft.result['id'],SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
