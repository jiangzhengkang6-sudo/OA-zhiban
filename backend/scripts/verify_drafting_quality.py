"""Bounded real-provider samples using application generators; never sends or publishes."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.schemas.document import DocumentInput
from app.schemas.email import EmailInput
from app.services import document_generator, email_generator, meeting_generator
from app.services import report_generator, work_task_generator
from app.services.contract_deepagents import analyze_long_contract
from app.services.contract_parser import parse_text
from app.services.document_templates import TEMPLATES, check_document
from app.services.document_service import _validated_draft as validate_document
from app.services.email_service import _validated_draft as validate_email


def checks_for(kind, value):
    """Small factual checks supplement, rather than replace, semantic review."""
    if kind == 'document':
        return dict(template_complete=not any(c.severity == 'error' for c in check_document(value['body'], TEMPLATES['notice'])),
            facts_present=all(word in value['body'] for word in ['18:00', '19:00', '保存']),
            cited=set(value['source_refs']) == {'input:notice'})
    if kind in {'email', 'meeting'}:
        actions = value['action_items']
        checks = dict(action_found=bool(actions) and any('清单' in a['title'] for a in actions),
            missing_metadata_not_invented=bool(actions) and all(a['assignee_candidate'] is None and
                a['due_at_candidate'] is None and a['needs_confirmation'] is True for a in actions),
            summary_grounded='维护' in value['summary'])
        if kind == 'email':
            checks['no_unapproved_commitment'] = not any(word in value['reply_body'] for word in
                ['我会', '我们将', '按时完成', '完成后向您反馈', '完成后反馈'])
        return checks
    if kind == 'work_task':
        return dict(task_found=bool(value) and any('清单' in a['title'] for a in value),
            identity_and_deadline_need_human=bool(value) and all(a['assignee_id'] is None and a['due_at'] is None for a in value),
            cited=bool(value) and all(a['source_refs'] == ['meeting:sample:v1'] for a in value))
    if kind == 'report':
        return dict(metric_bound=set(value['metric_refs']) == {'ticket_volume'},
            no_comparison_disclosed=any(word in value['summary'] for word in ['无对比', '缺少', '暂无', '无法', '不可', '没有', '不足']))
    if kind == 'contract':
        return dict(bounded_agent=value['engine'] == 'deepagents' and value['planned'] is True,
            all_blocks_read=value['blocks_read'] == list(range(value['blocks'])),
            evidence_returned=bool(value['observations']))
    raise ValueError('unknown_sample')


async def samples():
    source = dict(ref='input:notice', content='设备维护安排：2026-10-30 18:00 至 19:00，维护期间暂停使用，请提前保存工作。')
    payload = DocumentInput(template_id='notice', subject='设备维护通知', recipient='项目部门全体成员',
        deadline='2026-10-30 18:00 至 19:00', key_points=source['content'],
        distribution='项目部门站内公告', idempotency_key='quality-sample')
    async def document():
        result = await document_generator.generate(payload, TEMPLATES['notice'], [source])
        return validate_document(SimpleNamespace(source_snapshot=[source]), result).model_dump(mode='json')
    mail = EmailInput(subject='维护准备', sender='测试发件人', recipients=['项目部门'],
        body='设备维护已批准。\n请整理维护清单。负责人和截止时间尚未确定。', idempotency_key='quality-sample')
    lines = email_generator.source_lines(mail.body)
    async def email():
        result = await email_generator.generate(mail, lines)
        return validate_email(SimpleNamespace(source_snapshot=lines), result).model_dump(mode='json')
    segments = [dict(segment_id='s1', text='议题：设备维护准备'),
        dict(segment_id='s2', text='决定：维护期间暂停使用。'),
        dict(segment_id='s3', text='待办：整理维护清单，负责人和截止时间尚未确定。')]
    async def meeting():
        return await meeting_generator.generate(segments)
    async def work_task():
        return await work_task_generator.generate(dict(ref='meeting:sample:v1',
            content='待办：整理维护清单，负责人和截止时间尚未确定。'))
    async def report():
        result = await report_generator.generate(dict(metrics=[dict(metric_id='ticket_volume', name='工单数量',
            current=8, previous=0, comparison=None, comparison_status='no_comparison')], timezone='Asia/Shanghai'))
        return result.model_dump(mode='json')
    async def contract():
        return await analyze_long_contract(parse_text('付款：验收完成后支付合同款。\n违约：双方按约定承担违约责任。\n终止：经双方书面协商可终止。\n争议：先协商，未能解决时由约定法院处理。'))
    return [('document', document), ('email', email), ('meeting', meeting), ('work_task', work_task), ('report', report), ('contract', contract)]


async def main():
    settings = get_settings()
    if settings.llm_provider == 'mock':
        raise ValueError('real_provider_required')
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), primary=settings.llm_provider,
        fallback=settings.llm_fallback_provider, scope='six_project_authored_component_samples',
        business_owner_acceptance=False, production_acceptance=False, external_writes=False, results=[])
    for kind, action in await samples():
        started = monotonic()
        try:
            value = await asyncio.wait_for(action(), 150)
            checks = checks_for(kind, value)
            result = dict(kind=kind, output=value, checks=checks, passed=all(checks.values()), semantic_review='PENDING')
        except Exception as error:
            # No raw provider exception text, credentials or request headers in reports.
            result = dict(kind=kind, passed=False, error_type=type(error).__name__)
        result['seconds'] = round(monotonic() - started, 3)
        report['results'].append(result)
        print(kind + ': ' + ('PASS' if result['passed'] else 'FAIL'), flush=True)
    report['passed'] = all(r['passed'] for r in report['results'])
    output = Path(__file__).resolve().parents[2] / 'output/business-acceptance-private'
    output.mkdir(parents=True, exist_ok=True)
    path = output / ('drafting-quality-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Evidence: ' + path.name)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
