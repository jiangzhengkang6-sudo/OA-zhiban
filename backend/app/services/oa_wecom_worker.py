"""One durable batch per physical group send; personal authority stays independent."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select, or_
from ..models.oa_notification import OANotification, OANotificationDelivery as Delivery, OANotificationAttempt as Attempt, OAWecomBatch as Batch
from .identity_service import lock_tenant
from . import oa_wecom_policy as policy, oa_notification_source as sources


async def validate(db, row, worker):
    notification = await db.get(OANotification, row.notification_id)
    if not await sources.allowed(db, notification): return None, 'preflight_unavailable'
    info, reason = await policy.classify(db, notification, worker.get_settings())
    if not info: return None, reason
    if not await worker.resolve_contact(db, row, notification): return None, 'preflight_unavailable'
    row.wecom_event_key, row.wecom_business_key, row.wecom_category = info['event_key'], info['business_key'], info['category']
    return notification, None


async def finish_member(db, row, outcome, now):
    attempt = await db.scalar(select(Attempt).where(Attempt.tenant_id == row.tenant_id, Attempt.token == row.attempt_token))
    if attempt:
        attempt.state, attempt.finished_at = outcome, now
    row.lease_until = None


async def expire(db, tenant, now, delivery_id=None):
    query = select(Delivery).where(Delivery.tenant_id == tenant, Delivery.channel == 'wecom',
        Delivery.state == 'PROCESSING', Delivery.lease_until <= now)
    if delivery_id is not None: query = query.where(Delivery.id == delivery_id)
    rows = (await db.scalars(query.with_for_update())).all()
    batches = {row.wecom_batch_id for row in rows if row.wecom_batch_id}
    if batches:
        legacy = [row for row in rows if not row.wecom_batch_id]
        rows = legacy + list((await db.scalars(select(Delivery).where(Delivery.tenant_id == tenant,
            Delivery.wecom_batch_id.in_(batches), Delivery.state == 'PROCESSING').with_for_update())).all())
        for batch_id in batches:
            batch = await db.get(Batch, batch_id)
            batch.state, batch.finished_at = 'UNKNOWN', now
    for row in rows:
        row.state, row.last_code = 'UNKNOWN', 'lease_expired_possible_acceptance'
        await finish_member(db, row, 'UNKNOWN', now)


def payload(leader, notification, members, worker):
    claim = worker.payload(leader, notification, 'wecom-group')
    categories = sorted({row.wecom_category for row in members})
    claim['body'] = '\n'.join(policy.LABELS[category] for category in categories) + '\n' + worker.get_settings().notification_app_url
    claim['batch_id'] = leader.wecom_batch_id
    return claim


async def claim_one(factory, worker, *, tenant_id=None, now=None, delivery_id=None):
    now = now or datetime.now(timezone.utc)
    settings = worker.get_settings()
    async with factory() as db:
        query = select(Delivery.tenant_id).where(Delivery.channel == 'wecom', Delivery.state.in_(['PENDING', 'PROCESSING']))
        if tenant_id: query = query.where(Delivery.tenant_id == tenant_id)
        if delivery_id is not None: query = query.where(Delivery.id == delivery_id)
        tenants = (await db.scalars(query.distinct().order_by(Delivery.tenant_id))).all()
        for tenant in tenants:
            await lock_tenant(db, tenant)
            await expire(db, tenant, now, delivery_id)
            query = select(Delivery).where(Delivery.tenant_id == tenant, Delivery.channel == 'wecom', Delivery.state == 'PENDING',
                or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now))
            if delivery_id is not None: query = query.where(Delivery.id == delivery_id)
            rows = (await db.scalars(query.order_by(Delivery.created_at, Delivery.id).with_for_update())).all()
            eligible = []
            for row in rows:
                notification, reason = await validate(db, row, worker)
                if reason:
                    row.state, row.last_code = 'CANCELLED', reason
                else:
                    eligible.append((row, notification))
            for leader, notification in eligible:
                if leader.state != 'PENDING': continue
                group = [(row, item) for row, item in eligible if row.state == 'PENDING' and row.destination_hash == leader.destination_hash]
                # reserve_wecom also holds the cross-tenant robot lock until commit.
                if not await worker.reserve_wecom(db, leader, now):
                    for row, _ in group:
                        row.last_code, row.next_attempt_at = leader.last_code, leader.next_attempt_at
                    continue
                recent = await db.scalar(select(Batch).where(Batch.destination_hash == leader.destination_hash,
                    Batch.state != 'CANCELLED').order_by(Batch.created_at.desc()).limit(1))
                if recent and (recent.state == 'PROCESSING' or
                        max(recent.created_at, recent.finished_at or recent.created_at) + timedelta(seconds=settings.wecom_group_interval_seconds) > now):
                    for row, _ in group:
                        row.last_code = 'wecom_group_interval'
                        row.next_attempt_at = max(now + timedelta(seconds=1),
                            max(recent.created_at, recent.finished_at or recent.created_at) + timedelta(seconds=settings.wecom_group_interval_seconds))
                    continue
                members = []
                for row, item in group:
                    old_batch = await db.get(Batch,row.wecom_batch_id) if row.wecom_batch_id else None
                    manual = old_batch is not None and old_batch.state == 'UNKNOWN'
                    previous_query = select(Delivery).join(Batch, Batch.id == Delivery.wecom_batch_id).where(
                        Delivery.tenant_id == tenant, Delivery.id != row.id, Delivery.destination_hash == row.destination_hash,
                        Delivery.wecom_event_key == row.wecom_event_key, Batch.state.in_(['ACCEPTED', 'UNKNOWN', 'PROCESSING']))
                    if manual: previous_query = previous_query.where(Batch.id != old_batch.id)
                    previous = await db.scalar(previous_query.limit(1))
                    if previous:
                        row.state, row.last_code = 'CANCELLED', 'wecom_event_merged'
                        row.wecom_batch_id = previous.wecom_batch_id
                        continue
                    if row.wecom_category == 'nudge':
                        prior_nudge = await db.scalar(select(Delivery.id).join(Batch, Batch.id == Delivery.wecom_batch_id).where(
                            Delivery.tenant_id == tenant, Delivery.destination_hash == row.destination_hash,
                            Delivery.wecom_business_key == row.wecom_business_key, Delivery.wecom_category == 'nudge',
                            Batch.state.in_(['PROCESSING', 'ACCEPTED', 'UNKNOWN']),
                            or_(Batch.finished_at >= now - timedelta(seconds=settings.wecom_nudge_interval_seconds),
                                Batch.finished_at.is_(None), Batch.created_at >= now - timedelta(seconds=settings.wecom_nudge_interval_seconds))))
                        if prior_nudge:
                            row.state, row.last_code = 'CANCELLED', 'wecom_nudge_cooldown'
                            continue
                    members.append((row, item))
                if not members: continue
                batch = Batch(id=str(uuid4()), tenant_id=tenant, destination_hash=leader.destination_hash,
                    state='PROCESSING', lease_until=now + timedelta(minutes=2))
                db.add(batch)
                await db.flush()
                for row, _ in members:
                    row.state, row.wecom_batch_id = 'PROCESSING', batch.id
                    row.attempt_token, row.lease_until = str(uuid4()), batch.lease_until
                    row.attempt_count += 1
                    row.last_code = 'wecom_batch_processing'
                    db.add(Attempt(tenant_id=tenant, delivery_id=row.id, number=row.attempt_count,
                        token=row.attempt_token, state='PROCESSING', wecom_batch_id=batch.id))
                leader, notification = members[0]
                claim = payload(leader, notification, [row for row, _ in members], worker)
                await db.commit()
                return claim
            await db.commit()
    return None


async def batch_for(db, delivery_id, token):
    initial = await db.get(Delivery, delivery_id)
    if not initial or initial.attempt_token != token or not initial.wecom_batch_id: return None, None
    await lock_tenant(db, initial.tenant_id)
    row = await db.scalar(select(Delivery).where(Delivery.id == delivery_id).execution_options(populate_existing=True))
    if row.attempt_token != token: return None, None
    batch = await db.scalar(select(Batch).where(Batch.tenant_id == row.tenant_id,
        Batch.id == row.wecom_batch_id).with_for_update().execution_options(populate_existing=True))
    return (row, batch) if batch and batch.state == 'PROCESSING' else (None, None)


async def prepare_send(factory, worker, delivery_id, token, *, now=None):
    now = now or datetime.now(timezone.utc)
    async with factory() as db:
        leader, batch = await batch_for(db, delivery_id, token)
        if not batch: return None
        if batch.lease_until <= now:
            await expire(db, batch.tenant_id, now, leader.id)
            await db.commit()
            return None
        rows = (await db.scalars(select(Delivery).where(Delivery.tenant_id == batch.tenant_id,
            Delivery.wecom_batch_id == batch.id, Delivery.state == 'PROCESSING').with_for_update())).all()
        valid = []
        for row in rows:
            notification, reason = await validate(db, row, worker)
            if reason:
                row.state, row.last_code = 'CANCELLED', reason
                await finish_member(db, row, 'PERMANENT', now)
            else:
                valid.append((row, notification))
        if not valid:
            batch.state, batch.finished_at = 'CANCELLED', now
            await db.commit()
            return None
        # Keep the original leader token even if its personal authority was revoked.
        # Completion uses the batch receipt and only touches still-valid members.
        claim = payload(leader, valid[0][1], [row for row, _ in valid], worker)
        await db.commit()
        return claim


async def complete(factory, delivery_id, token, outcome, *, now=None):
    now = now or datetime.now(timezone.utc)
    if outcome not in {'ACCEPTED', 'TEMPORARY', 'PERMANENT', 'UNKNOWN'}: outcome = 'UNKNOWN'
    async with factory() as db:
        _, batch = await batch_for(db, delivery_id, token)
        if not batch: return False
        if batch.lease_until <= now: outcome = 'UNKNOWN'
        batch.state, batch.finished_at = outcome, now
        rows = (await db.scalars(select(Delivery).where(Delivery.tenant_id == batch.tenant_id,
            Delivery.wecom_batch_id == batch.id, Delivery.state == 'PROCESSING').with_for_update())).all()
        for row in rows:
            await finish_member(db, row, outcome, now)
            row.state = outcome if outcome in {'ACCEPTED', 'UNKNOWN'} else 'FAILED'
            if outcome == 'TEMPORARY' and row.attempt_count <= 3:
                row.state, row.next_attempt_at = 'PENDING', now + timedelta(minutes=(1, 5, 30)[row.attempt_count - 1])
            row.last_code = 'wecom_' + outcome.lower()
        await db.commit()
        return True
