import pytest
from sqlalchemy import select
from app.core.errors import AppException
from app.models.oa_leave import OALeaveBalance, OALeaveLedger
from tests.oa_support import oa_db
from tests.api.test_oa_leave_lifecycle import setup_leave, fields


async def test_explicit_quota_crossyear_atomicity_and_adjust_floor(oa_db):
    from app.services import oa_leave_service as leaves, oa_balance_service as service
    from app.schemas.oa_leave import BalanceAdjustment, LeaveDraftCreate, SubmitLeaveCommand
    async with oa_db() as db:
        admin,actor,workflow = await setup_leave(db)
        draft = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields('2026-12-31','2027-01-02')))
        await db.commit()
        request = SubmitLeaveCommand(operation_id='submit',expected_revision=1,requested_submission_version=1)
        with pytest.raises(AppException): await leaves.submit(db,actor,draft.result['id'],request)
        await db.rollback()
        await service.adjust(db,admin,BalanceAdjustment(operation_id='2026',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2026,total=1,reason='测试'))
        await db.commit()
        with pytest.raises(AppException): await leaves.submit(db,actor,draft.result['id'],request)
        await db.commit()
        row = await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert row.reserved == 0
        with pytest.raises(AppException): await service.adjust(db,actor,BalanceAdjustment(operation_id='self',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2027,total=2,reason='不能自行增加'))
        await db.rollback()
        await service.adjust(db,admin,BalanceAdjustment(operation_id='2027',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2027,total=2,reason='测试'))
        await db.commit()
        await leaves.submit(db,actor,draft.result['id'],request)
        await db.commit()
        rows = (await db.scalars(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id).order_by(OALeaveBalance.year))).all()
        assert [(r.year,r.total,r.used,r.reserved) for r in rows] == [(2026,1,0,1),(2027,2,0,2)]
        with pytest.raises(AppException): await service.adjust(db,admin,BalanceAdjustment(operation_id='reduce',expected_revision=2,user_id=actor.user_id,leave_type='annual',year=2027,total=1,reason='不能低于占用'))
        await db.commit()
        ledgers = (await db.scalars(select(OALeaveLedger).where(OALeaveLedger.tenant_id==actor.tenant_id))).all()
        assert sorted(l.kind for l in ledgers)==['ADJUST','ADJUST','RESERVE','RESERVE']
