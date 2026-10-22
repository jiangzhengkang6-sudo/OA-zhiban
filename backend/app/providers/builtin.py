"""Deterministic precheck for local applications with authority balance evidence."""

import asyncio
from datetime import datetime, timedelta, timezone
import math

from sqlalchemy import select

from ..adapters.factory import get_adapter
from ..adapters.oa_adapter import LeaveCase
from ..core.context import get_trace_id
from ..core.enums import ErrorCode
from ..models.leave_application import LeaveApplication
from ..tools import leave_tools

RULE_VERSION = 'builtin-v2'
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


def interval(start, end):
    """Legacy naive dates use the business timezone; aware dates preserve their instant."""
    def parse(value):
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return (result.replace(tzinfo=BUSINESS_TIMEZONE) if result.tzinfo is None
                else result.astimezone(BUSINESS_TIMEZONE))
    start, end = parse(start), parse(end)
    if end <= start:
        raise ValueError('结束时间必须晚于开始时间')
    return start, end


def requested_days(start, end):
    # Existing natural-day policy, calculated from local calendar dates.
    return float((end.date() - start.date()).days + 1)


def paused(items, dependency):
    label = {'balance': '假期余额', 'conflict': '已有请假记录', 'route': '组织审批路由'}[dependency]
    return {'items': items, 'passed': False, 'status': 'PAUSED', 'rule_version': RULE_VERSION,
            'error': {'code': ErrorCode.DEPENDENCY_FAILED.value, 'dependency': dependency,
                      'msg': label + '暂不可用，申请已安全暂停', 'trace_id': get_trace_id()}}


class BuiltinLeaveProvider:
    async def precheck(self, case: LeaveCase, *, session, application_id) -> dict:
        from ..services import leave_attachment_service
        fields = await leave_tools.validate_leave_form(_BuiltinAdapter(), case)
        items = [item for item in fields if item['item'] != 'attachment']
        if case.leave_type not in _BuiltinAdapter().get_field_dict()['leave_types']:
            items[0] = {'item': 'field', 'result': 'fail', 'reason': '未知假期类型',
                        'suggestion': '请选择年假、病假或事假'}
        items.append(await leave_attachment_service.precheck(
            session, application_id, case.attachments, case.leave_type == 'sick'))
        try:
            start, end = interval(case.start_at, case.end_at)
        except (TypeError, ValueError):
            items.extend([{'item': 'balance', 'result': 'fail', 'reason': '请先修正日期以计算申请天数'},
                          {'item': 'conflict', 'result': 'fail', 'reason': '结束时间必须晚于开始时间',
                           'suggestion': '请修改请假时间段'}])
            return self._result(items)
        days = requested_days(start, end)
        current = await session.get(LeaveApplication, application_id)
        if current is None or current.user_id != case.user_id:
            raise ValueError('请假申请不存在或申请人不匹配')
        rows = (await session.scalars(select(LeaveApplication).where(
            LeaveApplication.tenant_id == current.tenant_id,
            LeaveApplication.user_id == case.user_id,
            LeaveApplication.id != application_id,
            LeaveApplication.status.in_(('SUBMITTED', 'APPROVED')),
        ))).all()
        conflicts, held = [], 0.0
        try:
            for row in rows:
                other_start, other_end = interval(row.latest_fields.get('start_at'), row.latest_fields.get('end_at'))
                if start < other_end and other_start < end:
                    conflicts.append(row.business_id)
                if row.latest_fields.get('leave_type') == case.leave_type:
                    held += requested_days(other_start, other_end)
        except (TypeError, ValueError):
            items.append({'item': 'conflict', 'result': 'fail', 'reason': '已有有效申请材料无法验证',
                          'suggestion': '请联系管理员核对已有请假记录后重试'})
            return paused(items, 'conflict')
        conflict = {'item': 'conflict', 'result': 'fail' if conflicts else 'pass',
                    'reason': '与已有请假申请时间冲突：' + '、'.join(conflicts) if conflicts else '日期合法且无现有申请冲突',
                    'suggestion': '请调整开始或结束时间后重新提交' if conflicts else '',
                    'evidence': {'conflicting_business_ids': conflicts}}
        try:
            balance = await asyncio.wait_for(asyncio.to_thread(
                get_adapter().get_leave_balance, case.user_id, case.leave_type), timeout=10)
            balance = balance.model_dump()
            numbers = [float(balance[key]) for key in ('total', 'used', 'remaining')]
            if (balance.get('unit') != 'day' or balance.get('leave_type') != case.leave_type
                    or not all(math.isfinite(value) and value >= 0 for value in numbers)
                    or not math.isclose(numbers[0] - numbers[1], numbers[2], abs_tol=1e-6)):
                raise ValueError('余额返回值不可判定')
        except Exception:
            items.extend([{'item': 'balance', 'result': 'fail', 'reason': '假期余额服务暂不可用',
                           'suggestion': '请稍后重试或联系管理员'}, conflict])
            return paused(items, 'balance')
        available = max(numbers[2] - held, 0)
        checked = leave_tools.check_balance({'remaining': available}, case.leave_type, days)
        checked['evidence'] = {'provider': get_adapter().__class__.__name__, 'unit': 'day',
                               'duration_rule': 'inclusive-calendar-days-Asia/Shanghai',
                               'requested_days': days, 'provider_remaining': numbers[2],
                               'local_committed_days': held, 'available_days': available}
        items.extend([checked, conflict])
        return self._result(items)

    @staticmethod
    def _result(items):
        return {'items': items, 'passed': all(item['result'] == 'pass' for item in items),
                'rule_version': RULE_VERSION}


class _BuiltinAdapter:
    def get_field_dict(self):
        return {'leave_types': {
            'annual': {'required_fields': ['leave_type', 'start_at', 'end_at', 'reason'], 'attachment_required': False},
            'sick': {'required_fields': ['leave_type', 'start_at', 'end_at', 'reason'], 'attachment_required': True},
            'personal': {'required_fields': ['leave_type', 'start_at', 'end_at'], 'attachment_required': False},
        }}
