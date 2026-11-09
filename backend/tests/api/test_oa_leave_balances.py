import pytest
from sqlalchemy import select
from app.core.errors import AppException
from app.models.oa_leave import OALeaveBalance, OALeaveLedger
from tests.oa_support import oa_db
from tests.api.test_oa_leave_lifecycle import setup_leave, fields


@pytest.mark.parametrize('stored_type,requested_type', [('年假', 'annual'), ('annual', '年假')])
@pytest.mark.parametrize('finish', ['withdraw', 'approve'])
async def test_legacy_label_balance_settles_the_same_account(oa_db, stored_type, requested_type, finish):
    from app.schemas.oa_leave import LeaveDraftCreate, SubmitLeaveCommand, OACommand, BalanceAdjustment
    from app.services import oa_leave_service as leaves, oa_balance_service as balances
    from app.services.oa_workflow_scheduler import reconciliation_issues
    from app.models.oa_leave import OALeave
    from tests.unit.test_oa_workflow_definition import definition
    package = definition()
    package['form']['leave_types'] = [requested_type]
    async with oa_db() as db:
        admin, actor, workflow = await setup_leave(db, package=package)
        quota = await balances.adjust(db, admin, BalanceAdjustment(operation_id='quota', expected_revision=0,
            user_id=actor.user_id, leave_type=stored_type, year=2026, total=7, reason='初始化'))
        balance = await db.get(OALeaveBalance, quota.result['id'])
        balance.leave_type = stored_type
        draft = await leaves.create_draft(db, actor, LeaveDraftCreate(operation_id='create',
            workflow_definition_id=workflow, fields=fields('2026-10-29', '2026-10-30', leave_type=requested_type)))
        await db.commit()
        submitted = await leaves.submit(db, actor, draft.result['id'], SubmitLeaveCommand(
            operation_id='submit', expected_revision=1, requested_submission_version=1))
        await db.commit()
        await db.refresh(balance)
        assert (balance.total, balance.used, balance.reserved) == (7, 0, 2)
        leave = await db.get(OALeave, draft.result['id'])
        assert await reconciliation_issues(db, leave) == []
        if finish == 'withdraw':
            await leaves.withdraw(db, actor, draft.result['id'], OACommand(
                operation_id='withdraw', expected_revision=submitted.result['revision']))
        else:
            from app.services import oa_approval_service as approvals
            from app.schemas.oa_workflow import DecideNodeCommand
            node = (await approvals.list_items(db, admin, 'pending'))[0]['node_id']
            await approvals.decide(db, admin, node, DecideNodeCommand(
                operation_id='approve', expected_revision=1, action='approve'))
        await db.commit()
        await db.refresh(balance)
        assert (balance.total, balance.used, balance.reserved) == (7, 2 if finish == 'approve' else 0, 0)
        assert await reconciliation_issues(db, leave) == []
        ledgers = (await db.scalars(select(OALeaveLedger).where(OALeaveLedger.balance_id == balance.id))).all()
        assert {row.kind for row in ledgers} == {'ADJUST', 'RESERVE', 'CONSUME' if finish == 'approve' else 'RELEASE'}


async def test_adjust_reuses_legacy_account_and_creates_canonical_new_accounts(oa_db):
    from uuid import uuid4
    from app.schemas.oa_leave import BalanceAdjustment
    from app.services import oa_balance_service as service
    async with oa_db() as db:
        admin, actor, _ = await setup_leave(db)
        balance = OALeaveBalance(id=str(uuid4()), tenant_id=actor.tenant_id, user_id=actor.user_id,
            leave_type='年假', year=2026, total=7, used=0, reserved=0, revision=1)
        db.add(balance)
        await db.commit()
        payload = BalanceAdjustment(operation_id='adjust', expected_revision=1, user_id=actor.user_id,
            leave_type='annual', year=2026, total=8, reason='调整年假')
        changed = await service.adjust(db, admin, payload)
        await db.commit()
        assert changed.result['id'] == balance.id
        replay = await service.adjust(db, admin, payload)
        assert replay.replayed
        for code in ['病假', '护理假']:
            await service.adjust(db, admin, BalanceAdjustment(operation_id=code, expected_revision=0,
                user_id=actor.user_id, leave_type=code, year=2026, total=3, reason='初始化'))
        await db.commit()
        rows = await service.list_balances(db, admin, actor.user_id)
        assert {row['leave_type']: row['total'] for row in rows} == {'annual': 8, 'sick': 3, '护理假': 3}
        from app.adapters.builtin_gateway import BuiltinGateway
        from app.adapters.gateway import BridgeContext
        gateway = BuiltinGateway(BridgeContext(actor=admin, session=db))
        assert await gateway.get_leave_balance(actor.user_id, '年假') == await gateway.get_leave_balance(actor.user_id, 'annual')
        await db.refresh(balance)
        assert balance.leave_type == '年假'


async def test_duplicate_alias_accounts_block_adjustment_and_submission(oa_db):
    from uuid import uuid4
    from app.schemas.oa_leave import BalanceAdjustment, LeaveDraftCreate, SubmitLeaveCommand
    from app.services import oa_balance_service as service, oa_leave_service as leaves
    async with oa_db() as db:
        admin, actor, workflow = await setup_leave(db)
        for code in ['annual', '年假']:
            db.add(OALeaveBalance(id=str(uuid4()), tenant_id=actor.tenant_id, user_id=actor.user_id,
                leave_type=code, year=2026, total=7, used=0, reserved=0, revision=1))
        draft = await leaves.create_draft(db, actor, LeaveDraftCreate(operation_id='create',
            workflow_definition_id=workflow, fields=fields()))
        await db.commit()
        with pytest.raises(AppException, match='重复'):
            await service.adjust(db, admin, BalanceAdjustment(operation_id='adjust', expected_revision=1,
                user_id=actor.user_id, leave_type='annual', year=2026, total=8, reason='调整'))
        with pytest.raises(AppException, match='重复'):
            await leaves.submit(db, actor, draft.result['id'], SubmitLeaveCommand(
                operation_id='submit', expected_revision=1, requested_submission_version=1))
        await db.commit()
        rows = (await db.scalars(select(OALeaveBalance).where(OALeaveBalance.user_id == actor.user_id))).all()
        assert [(row.total, row.reserved) for row in rows] == [(7, 0), (7, 0)]


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
