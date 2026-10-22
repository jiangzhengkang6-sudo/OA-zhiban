import pytest
from sqlalchemy import select
from app.core.errors import AppException
from app.models.identity import OAMembership,OADepartment
from app.models.oa_leave import OALeaveBalance
from app.schemas.oa_leave import OACommand,SubmitLeaveCommand
from app.schemas.oa_workflow import DecideNodeCommand
from tests.oa_support import oa_db
from tests.api.test_oa_approval_modes import submitted
from tests.api.test_oa_leave_attachments import image_upload


async def test_node_file_context_expires_and_cc_cannot_open_materials(oa_db,monkeypatch):
    from app.services import oa_approval_service as approvals,oa_leave_service as leaves,oa_attachment_service as files
    from app.providers import file_scanner
    async def clean(content): return 'CLEAN'
    monkeypatch.setattr(file_scanner,'scan_bytes',clean)
    async with oa_db() as db:
        first,_,copied,actor,leave_id=await submitted(db,cc=True)
        await leaves.withdraw(db,actor,leave_id,OACommand(operation_id='withdraw',expected_revision=2))
        await db.commit()
        uploaded=await files.upload(db,actor,leave_id,image_upload(),operation_id='file',expected_revision=3)
        await db.commit()
        attachment_id=uploaded.result['attachment']['id']
        await leaves.submit(db,actor,leave_id,SubmitLeaveCommand(operation_id='new',expected_revision=4,requested_submission_version=2))
        await db.commit()
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        _,content=await approvals.download(db,first,node,attachment_id)
        assert content.startswith(b'\x89PNG')
        with pytest.raises(AppException): await approvals.download(db,copied,node,attachment_id)
        await db.rollback()
        await approvals.decide(db,first,node,DecideNodeCommand(operation_id='approve',expected_revision=1,action='approve'))
        await db.commit()
        for user in [first,copied]:
            with pytest.raises(AppException): await approvals.download(db,user,node,attachment_id)
            await db.rollback()
        assert len(await approvals.list_items(db,copied,'cc'))==1


async def test_current_department_change_revokes_node_materials_and_decision(oa_db):
    from app.services import oa_approval_service as approvals
    async with oa_db() as db:
        first,second,_,actor,leave_id=await submitted(db,mode='all')
        node=(await approvals.list_items(db,second,'pending'))[0]['node_id']
        dept=OADepartment(tenant_id=actor.tenant_id,name='调入部门')
        db.add(dept)
        await db.flush()
        membership=await db.get(OAMembership,(actor.tenant_id,second.user_id))
        membership.department_id=dept.id
        await db.commit()
        assert await approvals.list_items(db,second,'pending')==[]
        with pytest.raises(AppException): await approvals.node_context(db,second,node)
        await db.rollback()
        with pytest.raises(AppException):
            await approvals.decide(db,first,node,DecideNodeCommand(operation_id='invalidroute',expected_revision=1,action='approve'))
        await db.rollback()
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert (balance.used,balance.reserved)==(0,1)
