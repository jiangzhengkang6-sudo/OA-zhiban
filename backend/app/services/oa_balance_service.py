"""Explicit finite annual accounts and once-only integer-day settlement."""
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from ..core.leave_types import leave_type_aliases, leave_type_code, leave_type_label
from ..models.oa_leave import OALeaveBalance, OALeaveLedger
from ..models.identity import OAUser
from ..schemas.oa_leave import NormalizedLeaveFields
from .oa_access_service import (builtin_actor, authorize_oa, OAAccessTarget, user_department,
                               invalid, revision_conflict)
from .oa_command_service import OACommand, CommandOutcome, run_command


def view(row):
    return dict(id=row.id,user_id=row.user_id,leave_type=leave_type_code(row.leave_type),year=row.year,
                total=row.total,used=row.used,reserved=row.reserved,
                available=row.total-row.used-row.reserved,revision=row.revision)


def amounts(row):
    return {key:getattr(row,key) for key in ('total','used','reserved')}


async def find_balance(db, tenant_id, user_id, leave_type, year):
    # Keep existing account IDs and ledger links; never add two alias quotas together.
    rows = (await db.scalars(select(OALeaveBalance).where(OALeaveBalance.tenant_id == tenant_id,
        OALeaveBalance.user_id == user_id, OALeaveBalance.year == year,
        OALeaveBalance.leave_type.in_(leave_type_aliases(leave_type)))
        .order_by(OALeaveBalance.id).with_for_update().execution_options(populate_existing=True))).all()
    if len(rows) > 1:
        raise invalid(f'{year} 年{leave_type_label(leave_type)}存在重复额度账户，请由管理员核对台账')
    return rows[0] if rows else None


async def list_balances(db,actor,user_id=None):
    actor = await builtin_actor(db,actor)
    user_id = user_id or actor.user_id
    department = await user_department(db,actor.tenant_id,user_id)
    await authorize_oa(db,actor,'leave_balance','read',target=OAAccessTarget(actor.tenant_id,user_id,department))
    rows = (await db.scalars(select(OALeaveBalance).where(OALeaveBalance.tenant_id==actor.tenant_id,
        OALeaveBalance.user_id==user_id).order_by(OALeaveBalance.year,OALeaveBalance.leave_type))).all()
    return [view(row) for row in rows]


async def adjust(db,actor,payload):
    actor = await builtin_actor(db,actor)
    async def active_target():
        if not await db.scalar(select(OAUser.id).where(OAUser.tenant_id == actor.tenant_id,
                OAUser.id == payload.user_id, OAUser.status == 'active')):
            raise invalid('额度调整对象不存在或已停用')
    await active_target()
    department = await user_department(db,actor.tenant_id,payload.user_id)
    target = OAAccessTarget(actor.tenant_id,payload.user_id,department)
    leave_type = leave_type_code(payload.leave_type)
    target_id = str(uuid5(NAMESPACE_URL,':'.join(['oa:balance',actor.tenant_id,payload.user_id,leave_type,str(payload.year)])))
    # Preserve command keys already recorded before Chinese labels were normalized.
    command_target_id = str(uuid5(NAMESPACE_URL,':'.join(['oa:balance',actor.tenant_id,payload.user_id,payload.leave_type,str(payload.year)])))
    async def change(operation):
        await active_target()
        current = OAAccessTarget(actor.tenant_id,payload.user_id,await user_department(db,actor.tenant_id,payload.user_id))
        await authorize_oa(db,actor,'leave_balance','write',target=current)
        row = await find_balance(db, actor.tenant_id, payload.user_id, leave_type, payload.year)
        if row is None:
            if payload.expected_revision != 0: raise revision_conflict()
            row = OALeaveBalance(id=target_id,tenant_id=actor.tenant_id,user_id=payload.user_id,
                leave_type=leave_type,year=payload.year,total=0,used=0,reserved=0,revision=0)
            db.add(row)
        elif row.revision != payload.expected_revision:
            raise revision_conflict()
        if payload.total < row.used+row.reserved: raise invalid('额度不能低于已使用与已占用天数')
        before = amounts(row)
        row.total,row.revision = payload.total,row.revision+1
        await db.flush()
        db.add(OALeaveLedger(tenant_id=actor.tenant_id,balance_id=row.id,operation_id=operation.id,
            kind='ADJUST',total_delta=row.total-before['total'],used_delta=0,reserved_delta=0,
            before=before,after=amounts(row),reason=payload.reason))
        return CommandOutcome(result=view(row),detail=dict(reason=payload.reason,before=before,after=amounts(row)))
    return await run_command(db,actor,OACommand(kind='balance.adjust',target_id=command_target_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='leave_balance',target=target,
        applicant_id=payload.user_id),change)


async def settle(db,leave,version,operation,kind):
    if kind not in {'RESERVE','CONSUME','RELEASE'}: raise ValueError('Unknown settlement')
    form = NormalizedLeaveFields.model_validate(version.fields)
    for year,days in sorted(form.days_by_year.items()):
        row = await find_balance(db, leave.tenant_id, leave.applicant_id, form.leave_type, year)
        if row is None: raise invalid(f'请先由管理员初始化 {year} 年{leave_type_label(form.leave_type)}额度')
        existing = await db.scalar(select(OALeaveLedger.id).where(OALeaveLedger.tenant_id==leave.tenant_id,
            OALeaveLedger.balance_id==row.id,OALeaveLedger.leave_version_id==version.id,OALeaveLedger.kind==kind))
        if existing: continue
        if kind != 'RESERVE':
            other = 'RELEASE' if kind=='CONSUME' else 'CONSUME'
            if await db.scalar(select(OALeaveLedger.id).where(OALeaveLedger.tenant_id==leave.tenant_id,
                OALeaveLedger.balance_id==row.id,OALeaveLedger.leave_version_id==version.id,OALeaveLedger.kind==other)):
                raise invalid('该提交版本已结算')
        before = amounts(row)
        if kind=='RESERVE':
            if row.total-row.used-row.reserved < days: raise invalid('可用请假额度不足')
            row.reserved += days
        else:
            reservation = await db.scalar(select(OALeaveLedger.id).where(OALeaveLedger.tenant_id==leave.tenant_id,
                OALeaveLedger.balance_id==row.id,OALeaveLedger.leave_version_id==version.id,OALeaveLedger.kind=='RESERVE'))
            if not reservation or row.reserved < days: raise invalid('占用台账异常，需管理员核对')
            row.reserved -= days
            if kind=='CONSUME': row.used += days
        row.revision += 1
        after = amounts(row)
        db.add(OALeaveLedger(tenant_id=leave.tenant_id,balance_id=row.id,leave_version_id=version.id,
            operation_id=operation.id,kind=kind,total_delta=0,used_delta=after['used']-before['used'],
            reserved_delta=after['reserved']-before['reserved'],before=before,after=after,reason={'RESERVE':'提交占用','CONSUME':'审批通过','RELEASE':'撤回或驳回释放'}[kind]))
    await db.flush()
