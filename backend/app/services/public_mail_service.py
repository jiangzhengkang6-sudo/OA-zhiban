"""Shared mail authority is explicit membership, never inferred from department or role name."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, inspect, or_, select
from ..core.config import get_settings
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.public_mail import PublicMailbox, PublicMailboxMember, PublicMailMessage, PublicMailImport
from ..models.identity import OAUser
from ..models.work_task_batch import WorkTaskBatch
from ..providers import public_mail as transport
from ..schemas.email import EmailInput, EmailCommand
from ..schemas.public_mail import address
from ..schemas.work_task import WorkTaskSourceInput
from .authorization_service import require_ai_enabled, require_business_identity, require_permission
from . import audit_service, email_service, idempotency_service


def fail(message, status=403):
    code = {404: ErrorCode.NOT_FOUND, 409: ErrorCode.IDEMPOTENCY_CONFLICT,
            422: ErrorCode.INVALID_STATE, 503: ErrorCode.DEPENDENCY_FAILED}.get(status, ErrorCode.FORBIDDEN)
    raise AppException(code, message, http_status=status)


async def identity(session, actor):
    actor = await require_business_identity(actor, session=session)
    if actor.data_scope.get('identity_provider') != 'builtin':
        fail('公共邮箱仅支持正式身份账号')
    require_permission(actor, 'email', 'read')
    return actor


def configuration():
    settings = get_settings()
    try:
        address(settings.smtp_from)
    except ValueError:
        fail('请先配置有效的公共邮箱发件地址', 503)
    if not (settings.public_mailbox_enabled and settings.smtp_enabled and settings.smtp_host
            and settings.smtp_username and settings.smtp_password and settings.imap_host
            and (settings.smtp_starttls or settings.smtp_port == 465)):
        fail('公共邮箱未启用或收发配置不完整，请联系管理员', 503)
    return settings


def config_digest(settings):
    return idempotency_service.payload_digest(dict(address=settings.smtp_from,
        smtp_host=settings.smtp_host, username=settings.smtp_username,
        imap_host=settings.imap_host, imap_username=settings.imap_username or settings.smtp_username))


def check_binding(box):
    settings = configuration()
    if box.tenant_id != settings.auth_tenant_id or box.config_digest != config_digest(settings):
        fail('邮箱配置已变化，请先完成邮箱迁移，不可混用旧邮箱数据', 409)
    return settings


def can_setup(actor):
    return any(p['resource'] == 'organization' and p['action'] == 'write' and p['scope'] == 'department'
               for p in actor.data_scope.get('permissions', []))


def writable(actor):
    return any(p['resource'] == 'email' and p['action'] == 'write'
               for p in actor.data_scope.get('permissions', []))


async def access(session, actor, permission='read', *, lock=False):
    actor = await identity(session, actor)
    query = select(PublicMailbox).where(PublicMailbox.tenant_id == actor.tenant_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    box = await session.scalar(query)
    member = await session.get(PublicMailboxMember, (box.id, actor.user_id), populate_existing=True) if box else None
    if not member:
        fail('未获授权使用综合办公公共邮箱')
    if permission != 'read':
        require_permission(actor, 'email', 'write')
        if not getattr(member, 'can_' + permission):
            fail('没有此项公共邮箱操作权限')
    return actor, box, member


async def event(session, actor, box, action, message_id=None, **summary):
    await audit_service.audit(session, 'public_mail_' + action, actor_id=actor.user_id,
        target_type='public_mailbox', target_id=box.id, business_id=message_id or box.id,
        input_summary=summary or None)


async def status(session, actor):
    actor = await identity(session, actor)
    box = await session.scalar(select(PublicMailbox).where(PublicMailbox.tenant_id == actor.tenant_id))
    member = await session.get(PublicMailboxMember, (box.id, actor.user_id)) if box else None
    result = dict(provisioned=bool(box), authorized=bool(member), can_setup=not box and can_setup(actor) and writable(actor),
                  enabled=get_settings().public_mailbox_enabled)
    if member:
        result.update(id=box.id, name=box.name, address=box.address, synced_at=box.synced_at,
            revision=box.revision, can_process=member.can_process and writable(actor), can_send=member.can_send and writable(actor),
            can_manage=member.can_manage and writable(actor), user_id=actor.user_id)
    return result


async def setup(session, actor):
    actor = await identity(session, actor)
    require_permission(actor, 'email', 'write')
    if not can_setup(actor):
        fail('只有具备组织管理权限的成员可以初始化公共邮箱')
    settings = configuration()
    if actor.tenant_id != settings.auth_tenant_id:
        fail('邮箱配置不属于当前组织')
    from .identity_service import lock_tenant
    await lock_tenant(session, actor.tenant_id)
    box = await session.scalar(select(PublicMailbox).where(PublicMailbox.tenant_id == actor.tenant_id))
    if box:
        await access(session, actor, 'manage')
        return await status(session, actor)
    box = PublicMailbox(id='BOX-' + uuid4().hex[:20], tenant_id=actor.tenant_id,
        name=settings.public_mailbox_name[:128], address=settings.smtp_from, config_digest=config_digest(settings))
    session.add(box)
    await session.flush()
    session.add(PublicMailboxMember(mailbox_id=box.id, user_id=actor.user_id,
        can_process=True, can_send=True, can_manage=True))
    await session.flush()
    await event(session, actor, box, 'setup')
    return await status(session, actor)


async def member_options(session, actor):
    actor, box, _ = await access(session, actor, 'manage')
    from .identity_service import current_identity
    users = (await session.scalars(select(OAUser).where(OAUser.tenant_id == actor.tenant_id,
        OAUser.status == 'active').order_by(OAUser.display_name))).all()
    options = []
    for user in users:
        fresh = await current_identity(session, user)
        if not fresh or not any(p['resource'] == 'email' and p['action'] == 'read'
                                for p in fresh.data_scope.get('permissions', [])):
            continue
        options.append(dict(user_id=user.id, name=user.display_name,
            writable=any(p['resource'] == 'email' and p['action'] == 'write'
                         for p in fresh.data_scope.get('permissions', []))))
    members = (await session.scalars(select(PublicMailboxMember).where(PublicMailboxMember.mailbox_id == box.id))).all()
    return dict(revision=box.revision, users=options, members=[dict(user_id=m.user_id,
        can_process=m.can_process, can_send=m.can_send, can_manage=m.can_manage) for m in members])


async def save_members(session, actor, payload):
    actor, box, _ = await access(session, actor, 'manage', lock=True)
    if payload.expected_revision != box.revision:
        fail('成员授权已变化，请刷新', 409)
    options = {u['user_id']: u for u in (await member_options(session, actor))['users']}
    selected = {m.user_id: m for m in payload.members}
    if len(selected) != len(payload.members) or not any(m.can_manage for m in selected.values()):
        fail('成员不可重复，且必须保留至少一名邮箱管理员', 422)
    for member in selected.values():
        user = options.get(member.user_id)
        if not user or ((member.can_process or member.can_send or member.can_manage) and not user['writable']):
            fail('成员不可用或缺少邮件功能权限', 422)
    rows = (await session.scalars(select(PublicMailboxMember).where(PublicMailboxMember.mailbox_id == box.id))).all()
    for row in rows:
        if row.user_id not in selected:
            await session.delete(row)
    for user_id, member in selected.items():
        row = next((r for r in rows if r.user_id == user_id), None)
        if not row:
            row = PublicMailboxMember(mailbox_id=box.id, user_id=user_id)
            session.add(row)
        row.can_process, row.can_send, row.can_manage = member.can_process, member.can_send, member.can_manage
    box.revision += 1
    await event(session, actor, box, 'members_updated', member_count=len(selected))
    return dict(revision=box.revision)


async def message(session, box, message_id, *, lock=False):
    query = select(PublicMailMessage).where(PublicMailMessage.id == message_id, PublicMailMessage.mailbox_id == box.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if not row:
        fail('邮件不存在', 404)
    return row


async def response(session, actor, box, row, *, detail=False):
    await session.flush()
    if inspect(row).expired_attributes:
        await session.refresh(row)
    result = {key: getattr(row, key) for key in ('id', 'subject', 'sender', 'recipients', 'direction', 'status',
        'claimed_by', 'created_by', 'sent_by', 'version', 'sent_at', 'created_at', 'updated_at', 'reply_to_id')}
    for key in ('claimed_by', 'created_by', 'sent_by'):
        user = await session.scalar(select(OAUser).where(OAUser.id == getattr(row, key), OAUser.tenant_id == box.tenant_id)) if getattr(row, key) else None
        result[key + '_name'] = user.display_name if user else None
    if detail:
        result.update(body=row.body, attachments=row.attachments)
        link = await session.get(PublicMailImport, (row.id, actor.user_id))
        result['analysis_id'] = link.email_id if link else None
    return result


async def listing(session, actor, folder='inbox', search='', page=1):
    actor, box, _ = await access(session, actor)
    query = select(PublicMailMessage).where(PublicMailMessage.mailbox_id == box.id)
    if folder == 'drafts':
        query = query.where(PublicMailMessage.direction == 'outgoing', PublicMailMessage.status == 'DRAFT')
    elif folder == 'sent':
        query = query.where(PublicMailMessage.direction == 'outgoing', PublicMailMessage.status != 'DRAFT')
    else:
        query = query.where(PublicMailMessage.direction == 'incoming')
        if folder == 'pending':
            query = query.where(PublicMailMessage.status != 'DONE')
    if search.strip():
        needle = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')[:200] + '%'
        query = query.where(or_(PublicMailMessage.subject.ilike(needle, escape='\\'), PublicMailMessage.sender.ilike(needle, escape='\\')))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.order_by(PublicMailMessage.created_at.desc(), PublicMailMessage.id).offset((page-1)*20).limit(20))).all()
    return dict(items=[await response(session, actor, box, r) for r in rows], total=total, page=page)


async def detail(session, actor, message_id):
    actor, box, _ = await access(session, actor)
    row = await message(session, box, message_id)
    await event(session, actor, box, 'viewed', row.id)
    return await response(session, actor, box, row, detail=True)


async def sync(session, actor):
    actor, box, _ = await access(session, actor, 'process', lock=True)
    settings = check_binding(box)
    try:
        batch = await asyncio.to_thread(transport.receive, settings, box.uid_validity, box.last_uid)
    except Exception:
        fail('收信失败，请检查 IMAP 服务、授权码及网络连接', 503)
    await access(session, actor, 'process')
    added = 0
    for item in batch['messages']:
        existing = await session.scalar(select(PublicMailMessage.id).where(PublicMailMessage.mailbox_id == box.id,
            PublicMailMessage.remote_key == item['remote_key']))
        if not existing:
            session.add(PublicMailMessage(id='PUBMAIL-' + uuid4().hex[:20], mailbox_id=box.id,
                direction='incoming', status='NEW', **item))
            added += 1
    box.uid_validity, box.last_uid = batch['validity'], batch['last_uid']
    box.synced_at = datetime.now(timezone.utc)
    await event(session, actor, box, 'synced', added=added)
    return dict(added=added, has_more=batch['has_more'], synced_at=box.synced_at)


def expect(row, version):
    if row.version != version:
        fail('邮件已被其他成员更新，请刷新后重试', 409)


def claim_guard(actor, row):
    if row.claimed_by and row.claimed_by != actor.user_id:
        fail('邮件已由其他成员认领，请先协调处理', 409)


async def save_draft(session, actor, payload, message_id=None):
    actor, box, _ = await access(session, actor, 'send', lock=True)
    digest = idempotency_service.payload_digest(payload.model_dump(exclude={'idempotency_key', 'expected_version'}))
    if message_id:
        row = await message(session, box, message_id, lock=True)
        expect(row, payload.expected_version)
        if row.direction != 'outgoing' or row.status != 'DRAFT':
            fail('只有未发送草稿可以编辑', 422)
        if row.reply_to_id != payload.reply_to_id:
            fail('不能更改回复来源', 422)
    else:
        row = await session.scalar(select(PublicMailMessage).where(PublicMailMessage.mailbox_id == box.id,
            PublicMailMessage.created_by == actor.user_id, PublicMailMessage.create_key == payload.idempotency_key))
        if row:
            if row.create_digest != digest:
                fail('相同请求对应不同邮件内容', 409)
            return await response(session, actor, box, row, detail=True)
        row = PublicMailMessage(id='PUBMAIL-' + uuid4().hex[:20], mailbox_id=box.id, direction='outgoing',
            status='DRAFT', created_by=actor.user_id, create_key=payload.idempotency_key, create_digest=digest,
            message_id=f'<oa-{uuid4().hex}@{box.address.rsplit("@", 1)[-1]}>', sender=box.address, attachments=[])
    if payload.reply_to_id:
        source = await message(session, box, payload.reply_to_id, lock=True)
        if source.direction != 'incoming':
            fail('回复来源必须是收到的邮件', 422)
        claim_guard(actor, source)
        if not source.claimed_by:
            source.claimed_by, source.status = actor.user_id, 'PROCESSING'
            source.version += 1
    row.subject, row.recipients, row.body = payload.subject, payload.recipients, payload.body
    row.reply_to_id = payload.reply_to_id
    row.version = (row.version or 0) + 1
    session.add(row)
    await session.flush()
    await event(session, actor, box, 'draft_saved', row.id)
    return await response(session, actor, box, row, detail=True)


async def action(session, actor, message_id, payload):
    permission = 'send' if payload.action == 'send' else 'process'
    actor, box, member = await access(session, actor, permission, lock=True)
    row = await message(session, box, message_id, lock=True)
    if payload.action == 'send' and row.status in {'SENDING', 'ACCEPTED', 'UNKNOWN', 'FAILED'}:
        return await response(session, actor, box, row, detail=True)
    expect(row, payload.expected_version)
    if payload.action == 'send':
        if not payload.confirmed or row.status != 'DRAFT' or row.direction != 'outgoing':
            fail('请核对收件人和正文并明确确认发送', 422)
        settings = check_binding(box)
        if row.reply_to_id:
            source = await message(session, box, row.reply_to_id, lock=True)
            claim_guard(actor, source)
        else:
            source = None
        data = dict(recipients=row.recipients, subject=row.subject, body=row.body,
            message_id=row.message_id, in_reply_to=source.message_id if source and source.message_id.startswith('<')
            and '\r' not in source.message_id and '\n' not in source.message_id else None)
        row.status, row.sent_by = 'SENDING', actor.user_id
        row.version += 1
        await event(session, actor, box, 'send_started', row.id)
        # The durable intent MUST precede SMTP. A crash leaves SENDING, never an automatic retry.
        await session.commit()
        outcome = await asyncio.to_thread(transport.send_message, settings, data)
        # A transport receipt is a trusted internal write in an independent transaction.
        # Revocation can deny the response, but must not erase a completed SMTP outcome.
        async with type(session)(bind=session.bind, expire_on_commit=False) as receipt_db:
            receipt = await message(receipt_db, box, message_id, lock=True)
            receipt.status = outcome if outcome in {'ACCEPTED', 'FAILED', 'UNKNOWN'} else 'UNKNOWN'
            receipt.sent_at = datetime.now(timezone.utc)
            receipt.version += 1
            await event(receipt_db, actor, box, 'send_result', receipt.id, outcome=receipt.status)
            await receipt_db.commit()
        await session.refresh(row)
        await access(session, actor, 'send')
    else:
        if row.direction != 'incoming':
            fail('此操作只适用于收件箱', 422)
        if payload.action == 'release' and member.can_manage:
            row.claimed_by, row.status = None, 'NEW'
        else:
            claim_guard(actor, row)
            if payload.action == 'claim':
                if row.status == 'DONE':
                    fail('请先重新打开已处理邮件', 422)
                row.claimed_by, row.status = actor.user_id, 'PROCESSING'
            elif payload.action == 'release':
                row.claimed_by, row.status = None, 'NEW'
            elif payload.action == 'complete':
                row.claimed_by, row.status = actor.user_id, 'DONE'
            elif payload.action == 'reopen':
                row.claimed_by, row.status = None, 'NEW'
        row.version += 1
        await event(session, actor, box, payload.action, row.id)
    return await response(session, actor, box, row, detail=True)


async def import_analysis(session, actor, message_id):
    require_ai_enabled()
    actor, box, _ = await access(session, actor, 'process', lock=True)
    row = await message(session, box, message_id, lock=True)
    if row.direction != 'incoming':
        fail('仅收件可以录入分析', 422)
    claim_guard(actor, row)
    link = await session.get(PublicMailImport, (row.id, actor.user_id))
    if link:
        return dict(email_id=link.email_id)
    result = await email_service.create_email(session, actor, EmailInput(subject=row.subject, sender=row.sender,
        recipients=row.recipients or [box.address], body=row.body, attachments=row.attachments,
        external_contact=True, idempotency_key='public-mail-' + row.id))
    session.add(PublicMailImport(message_id=row.id, user_id=actor.user_id, email_id=result.email_id))
    row.claimed_by, row.status = actor.user_id, 'PROCESSING'
    row.version += 1
    await event(session, actor, box, 'imported', row.id, email_id=result.email_id)
    await session.commit()
    await email_service.analyze(session, actor, result.email_id, EmailCommand(idempotency_key='public-mail-analyze-' + row.id))
    return dict(email_id=result.email_id)


async def task_source(session, actor, message_id):
    actor, box, _ = await access(session, actor)
    row = await message(session, box, message_id)
    if row.direction != 'incoming':
        fail('仅收件可作为任务来源', 422)
    content = row.body
    digest = sha256(content.encode()).hexdigest()
    return dict(ref=f'email:{row.id}:{digest}', source_type='email', source_id=row.id, version=digest,
        title=row.subject, content=content, content_hash=digest, action_items=[])


async def claim_task_source(session, actor, message_id):
    """Also guard direct task-batch creation, not only the mailbox conversion route."""
    actor, box, _ = await access(session, actor, 'process', lock=True)
    row = await message(session, box, message_id, lock=True)
    if row.direction != 'incoming':
        fail('仅收件可作为任务来源', 422)
    claim_guard(actor, row)
    if not row.claimed_by:
        row.claimed_by, row.status = actor.user_id, 'PROCESSING'
        row.version += 1
        await event(session, actor, box, 'claim', row.id)


async def convert_task(session, actor, message_id):
    require_ai_enabled()
    actor = await identity(session, actor)
    from .identity_service import lock_tenant
    await lock_tenant(session, actor.tenant_id)
    actor, box, _ = await access(session, actor, 'process', lock=True)
    row = await message(session, box, message_id, lock=True)
    claim_guard(actor, row)
    from . import work_task_service
    require_permission(actor, 'work_task', 'write')
    previous = await session.scalar(select(WorkTaskBatch).where(WorkTaskBatch.tenant_id == actor.tenant_id,
        WorkTaskBatch.owner_id == actor.user_id, WorkTaskBatch.source_type == 'email',
        WorkTaskBatch.source_id == row.id).order_by(WorkTaskBatch.created_at).limit(1))
    if previous:
        return dict(batch_id=previous.batch_id)
    result = await work_task_service.create_batch(session, actor, WorkTaskSourceInput(source_type='email',
        source_id=row.id, idempotency_key='public-mail-task-' + row.id))
    await event(session, actor, box, 'task_draft_created', row.id, batch_id=result.batch_id)
    return dict(batch_id=result.batch_id)
