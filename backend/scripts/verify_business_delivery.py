"""One authorized, self-owned acceptance ticket; never drain a tenant queue.

Run without --send for a read-only readiness snapshot. Sending requires the
existing member, authorized mailbox and an explicit run identifier. Reuse that
identifier after interruption; UNKNOWN outcomes are never resent automatically.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.context import set_current_user
from app.db.migrations import assert_schema_current
from app.db.session import async_session_factory, engine
from app.models.identity import OAUser
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.oa_leave import OALeave
from app.models.oa_notification import OAUserContact, OANotification, OANotificationDelivery
from app.models.oa_ticket import OATicket
from app.models.oa_workflow import OAWorkflowOutbox, OAWorkflowEvent, OAWorkflowOperation
from app.providers import smtp, wecom
from app.schemas.oa_ticket import FormalTicketProposal, TicketHandleCommand
from app.services import oa_notification_service as notifications, oa_notification_worker as worker
from app.services import oa_ticket_service as tickets
from app.services.identity_service import current_identity

OUTPUT = Path(__file__).resolve().parents[2] / 'output' / 'business-acceptance-private'


async def snapshot():
    settings = get_settings()
    async with async_session_factory() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        connection = await db.connection()
        await connection.run_sync(assert_schema_current)
        members = await db.scalar(select(func.count()).select_from(OAUser).where(
            OAUser.tenant_id == settings.auth_tenant_id, OAUser.status == 'active'))
        leaves = await db.scalar(select(func.count()).select_from(OALeave).where(
            OALeave.tenant_id == settings.auth_tenant_id))
        published = await db.scalar(select(func.count()).select_from(KnowledgeVersion).join(
            KnowledgeSource, KnowledgeSource.id == KnowledgeVersion.source_id).where(
            KnowledgeSource.tenant_id == settings.auth_tenant_id, KnowledgeVersion.status == 'published'))
        database = (await db.execute(text('select current_database()'))).scalar_one()
        return dict(database=database, active_members=members, leave_rows=leaves,
                    published_knowledge_versions=published, real_business_provenance='UNVERIFIED',
                    department_pilot='UNVERIFIED', production_acceptance=False)


async def deliver(options):
    settings = get_settings()
    if settings.auth_provider != 'builtin' or settings.oa_provider != 'builtin':
        raise ValueError('builtin_identity_and_oa_required')
    if not settings.smtp_enabled or not settings.smtp_starttls or not settings.wecom_enabled:
        raise ValueError('secure_real_transports_required')
    async with async_session_factory() as db:
        connection = await db.connection()
        await connection.run_sync(assert_schema_current)
        user = await db.scalar(select(OAUser).where(OAUser.tenant_id == settings.auth_tenant_id,
            OAUser.normalized_username == options.username, OAUser.status == 'active'))
        actor = await current_identity(db, user)
        set_current_user(actor)
        contact = await db.scalar(select(OAUserContact).where(OAUserContact.tenant_id == actor.tenant_id,
            OAUserContact.user_id == actor.user_id))
        if not contact or not contact.enabled or contact.email != options.expected_recipient:
            raise ValueError('existing_recipient_authorization_required')
        if not actor.depts or not wecom.destination(settings, actor.tenant_id, actor.depts[0]):
            raise ValueError('recipient_group_scope_mismatch')
        if not contact.wecom_enabled and not options.enable_own_wecom:
            raise ValueError('explicit_self_wecom_consent_required')
        if not contact.wecom_enabled:
            await notifications.save_contact(db, actor, actor.user_id, email=contact.email, enabled=True,
                wecom_enabled=True, operation_id=options.run_id + '-consent')
        proposal = FormalTicketProposal(operation_id=options.run_id + '-create', category='系统验收',
            impact='个人', summary='核验本项目业务邮件与企业微信群通知，并由本人核对收件结果。验收编号：' + options.run_id)
        assignment = await tickets.assignment(db, actor, actor.depts[0], proposal.category, proposal.impact)
        if assignment['assignee_id'] not in {None, actor.user_id}:
            raise ValueError('acceptance_must_not_assign_other_members')
        previous = await tickets.get_result(db, actor, proposal.operation_id)
        if previous is None:
            prepared = await tickets.prepare(db, actor, proposal)
            created = await tickets.create_or_merge(db, actor, proposal, confirmation_id=prepared['confirmation_id'])
            ticket_id = created.result['id']
        else:
            ticket_id = previous['id']
        ticket = await db.get(OATicket, ticket_id)
        if ticket.assignee_id is None and ticket.state == 'OPEN':
            await tickets.handle(db, actor, ticket_id, TicketHandleCommand(action='claim',
                operation_id=options.run_id + '-claim', expected_revision=ticket.revision))
        if ticket.assignee_id != actor.user_id:
            raise ValueError('acceptance_ticket_owner_changed')
        outboxes = (await db.scalars(select(OAWorkflowOutbox).join(
            OAWorkflowEvent, OAWorkflowEvent.id == OAWorkflowOutbox.event_id).join(
            OAWorkflowOperation, OAWorkflowOperation.id == OAWorkflowEvent.operation_id).where(
            OAWorkflowOutbox.tenant_id == actor.tenant_id, OAWorkflowOutbox.recipient_id == actor.user_id,
            OAWorkflowOperation.actor_id == actor.user_id,
            OAWorkflowOperation.operation_id.in_([options.run_id + '-create', options.run_id + '-claim'])))).all()
        if len(outboxes) != 1:
            raise ValueError('single_acceptance_notification_required')
        await notifications.dispatch(db, tenant_id=actor.tenant_id, outbox_id=outboxes[0].id)
        notification = await db.scalar(select(OANotification).where(
            OANotification.tenant_id == actor.tenant_id, OANotification.source_outbox_id == outboxes[0].id,
            OANotification.recipient_id == actor.user_id))
        rows = (await db.scalars(select(OANotificationDelivery).where(
            OANotificationDelivery.tenant_id == actor.tenant_id,
            OANotificationDelivery.notification_id == notification.id))).all()
        if {row.channel for row in rows} != {'inbox', 'smtp', 'wecom'}:
            raise ValueError('all_three_channels_required')
        delivery_ids = {row.channel: row.id for row in rows}
        await db.commit()

    timings = {}
    for channel, sender in [('smtp', smtp.send), ('wecom', wecom.send)]:
        claim = await worker.claim_one(async_session_factory, tenant_id=actor.tenant_id,
                                       channel=channel, delivery_id=delivery_ids[channel])
        if not claim:
            continue
        claim = await worker.prepare_send(async_session_factory, claim['id'], claim['token'])
        if not claim:
            continue
        started = monotonic()
        try:
            outcome = await asyncio.to_thread(sender, claim)
        except Exception:
            outcome = 'UNKNOWN'
        recorded = await worker.complete(async_session_factory, claim['id'], claim['token'], outcome)
        timings[channel] = dict(provider_seconds=round(monotonic() - started, 3), recorded=recorded)
    async with async_session_factory() as db:
        rows = (await db.scalars(select(OANotificationDelivery).where(
            OANotificationDelivery.id.in_(delivery_ids.values())))).all()
        inbox = await notifications.list_inbox(db, actor)
        return dict(run_id=options.run_id, ticket_id=ticket_id, notification_id=notification.id,
            channels={row.channel: dict(state=row.state, attempt_count=row.attempt_count,
                message_id=row.message_id, **timings.get(row.channel, {})) for row in rows},
            inbox_visible=any(item['id'] == notification.id for item in inbox),
            recipient_confirmation={'smtp': 'UNVERIFIED', 'wecom': 'UNVERIFIED'},
            member_receipt_acceptance=False, department_pilot='UNVERIFIED', production_acceptance=False)


async def run(options):
    try:
        report = await deliver(options) if options.send else await snapshot()
        report['checked_at'] = datetime.now(timezone.utc).isoformat()
        if options.send:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            # Append evidence: a rerun must not erase an earlier provider timing/receipt.
            with (OUTPUT / (options.run_id + '.jsonl')).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(report, ensure_ascii=False) + '\n')
        return report
    finally:
        set_current_user(None)
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--username')
    parser.add_argument('--expected-recipient')
    parser.add_argument('--run-id')
    parser.add_argument('--enable-own-wecom', action='store_true')
    options = parser.parse_args()
    if options.send and (not options.username or not options.expected_recipient or
            not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', options.run_id or '')):
        parser.error('--send requires username, authorized recipient and a safe run-id (max 40 chars)')
    try:
        report = asyncio.run(run(options))
    except Exception:
        print(json.dumps({'error': 'business_acceptance_incomplete', 'production_acceptance': False}))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if options.send and (not report['inbox_visible'] or any(
        item['state'] != 'ACCEPTED' for item in report['channels'].values())) else 0


if __name__ == '__main__':
    sys.exit(main())
