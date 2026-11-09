"""Private, versioned contract review; business ledger owns human decisions."""
import asyncio
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select, func, or_
from ..core.context import get_trace_id
from ..core.config import get_settings
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from ..models.contract_record import ContractRecord
from ..models.contract_source import ContractSource
from ..models.contract_review_version import ContractReviewVersion
from ..models.idempotency_record import IdempotencyRecord
from ..schemas.command import CommandEnvelope
from ..adapters.factory import get_adapter
from ..providers.file_scanner import scan_bytes
from .authorization_service import require_business_identity, require_permission, resource_clause, business_boundary
from . import idempotency_service, audit_service, policy_service, degradation_service, runtime_trace_service
from .contract_parser import parse_text, parse_upload, validate_evidence, MAX_BYTES


async def _identity(session, actor):
    fresh = await require_business_identity(actor, session=session)
    require_permission(fresh, 'contract', 'read')
    return fresh


async def _reviewer(session, actor, reviewer_id):
    try:
        from ..providers.identity import IdentityResolver
        context = await IdentityResolver().resolve(reviewer_id, session=session)
    except AppException:
        raise
    except Exception:
        raise AppException(ErrorCode.DEPENDENCY_FAILED,'复核人身份暂不可用',http_status=502) from None
    if not context or context.tenant_id != actor.tenant_id:
        raise AppException(ErrorCode.FORBIDDEN,'指定复核人须为同租户有效成员',http_status=403)
    if context.data_scope.get('identity_provider') == 'builtin':
        context = await require_business_identity(context, session=session)
        require_permission(context, 'contract', 'read')
        require_permission(context, 'contract', 'write')
    elif not set(context.roles).intersection({'approver','admin'}):
        raise AppException(ErrorCode.FORBIDDEN,'指定复核人须为同租户审批人或管理员',http_status=403)
    return context


async def reviewer_options(session, actor):
    from ..models.identity import OAUser
    from .identity_service import current_identity
    actor = await _identity(session, actor)
    require_permission(actor, 'contract', 'write')
    if actor.data_scope.get('identity_provider') != 'builtin':
        raise AppException(ErrorCode.FORBIDDEN, '成员目录仅适用于正式账号', http_status=403)
    users = (await session.scalars(select(OAUser).where(OAUser.tenant_id == actor.tenant_id,
        OAUser.status == 'active').order_by(OAUser.display_name, OAUser.id))).all()
    result = []
    for user in users:
        member = await current_identity(session, user)
        try:
            require_permission(member, 'contract', 'read')
            require_permission(member, 'contract', 'write')
        except AppException:
            continue
        result.append(dict(id=user.id, name=user.display_name))
    return result


def _scope(actor):
    participant = ContractRecord.owner_id == actor.user_id
    if actor.data_scope.get('identity_provider') == 'builtin' or set(actor.roles).intersection({'approver','admin'}):
        participant = or_(participant, ContractRecord.reviewer_id == actor.user_id)
    return (ContractRecord.tenant_id == actor.tenant_id, participant)


async def _owned(session, actor, contract_id, *, lock=False):
    actor = await _identity(session, actor)
    query = select(ContractRecord).where(ContractRecord.contract_id == contract_id, *_scope(actor))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(query)
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND,'合同不存在',http_status=404)
    return record


async def _available(session, actor, record=None):
    if not await policy_service.is_scene_enabled(session,'contract',actor.user_id,actor.depts[0] if actor.depts else '',actor.tenant_id):
        raise AppException(ErrorCode.DEGRADED,'合同智能路径已关闭',http_status=503)
    state = await degradation_service.resolve(session,scene='contract',user=actor)
    if state:
        action = state.new_task_action if record is None or record.created_at >= state.created_at else state.inflight_action
        if action != 'continue':
            raise AppException(ErrorCode.DEGRADED,'合同场景处于降级状态',http_status=503)


async def _claim(session, actor, resource, action, payload, key):
    return await idempotency_service.claim(session,CommandEnvelope(command_id=uuid4(),idempotency_key=key,
        actor_id=actor.user_id,tenant_id=actor.tenant_id,resource_type='contract',resource_id=resource,
        trace_id=get_trace_id() or uuid4().hex,payload={'action':action,**payload}))


async def _source(session, record):
    return await session.scalar(select(ContractSource).where(ContractSource.contract_id == record.id))


def _actions(record, actor):
    if record.status in {'CONFIRMED','REJECTED'}:
        return []
    if actor.data_scope.get('identity_provider') == 'builtin' and not any(
        p['resource'] == 'contract' and p['action'] == 'write' for p in actor.data_scope.get('permissions', [])
    ):
        return []
    actions = []
    if actor.user_id == record.owner_id:
        actions = {'CREATED':['review','rescan'], 'PAUSED':['retry'], 'DRAFT_READY':['save','review']}.get(record.status,[])
        if record.status == 'PROCESSING' and record.updated_at < datetime.now(timezone.utc) - timedelta(seconds=130):
            actions = ['retry']
    reviewer_authority = actor.data_scope.get('identity_provider') == 'builtin' or set(actor.roles).intersection({'approver','admin'})
    if actor.user_id == record.reviewer_id and reviewer_authority and record.status == 'DRAFT_READY':
        actions += ['confirm','reject']
    return actions


async def _response(session, record, actor):
    from ..models.identity import OAUser
    reviewer_name = await session.scalar(select(OAUser.display_name).where(
        OAUser.id == record.reviewer_id, OAUser.tenant_id == actor.tenant_id)) if actor.data_scope.get('identity_provider') == 'builtin' else None
    source = await _source(session,record)
    version = await session.scalar(select(ContractReviewVersion).where(ContractReviewVersion.contract_id == record.id,
        ContractReviewVersion.version == record.current_version)) if record.current_version else None
    return dict(contract_id=record.contract_id,thread_id=str(record.thread_id),title=record.title,status=record.status,
        version=record.current_version,reviewer_id=record.reviewer_id,reviewer_name=reviewer_name,owner_id=record.owner_id,
        available_actions=_actions(record,actor),source_id=str(source.id),source_hash=source.sha256,
        scan_status=source.scan_status,paragraphs=source.paragraphs,source_text=source.text,
        draft=version.draft if version else None,node_trace=record.node_state.get('node_trace',[]),
        confirmation=record.confirmation,created_at=record.created_at.isoformat(),updated_at=record.updated_at.isoformat(),
        error={'message':record.error_message,'trace_id':record.error_trace_id} if record.status == 'PAUSED' else None,
        external_writes=False)


async def _finish(session, record, actor, command, action):
    thread = await session.get(AgentThread,record.thread_id)
    thread.status = {'CREATED':'DRAFT','PROCESSING':'PRECHECK','DRAFT_READY':'WAITING_HUMAN','PAUSED':'PAUSED',
        'CONFIRMED':'COMPLETED','REJECTED':'REJECTED'}[record.status]
    thread.waiting_since = None
    thread.error_msg = record.error_message
    thread.error_code = 'CONTRACT_FAILED' if record.status == 'PAUSED' else None
    await audit_service.audit(session,'contract_' + action,
        thread_id=record.thread_id,business_id=record.contract_id,actor_id=actor.user_id,target_type='contract',target_id=record.contract_id,
        input_summary={'source_hash':(await _source(session,record)).sha256},output_summary={'status':record.status,'version':record.current_version})
    await session.flush()
    await session.refresh(record)
    result = await _response(session,record,await _identity(session, actor))
    await idempotency_service.complete(session,command,result)
    return result


@business_boundary('contract', 'write')
async def create_contract(session, actor, payload, *, upload=None):
    actor = await _identity(session, actor)
    await _reviewer(session, actor,payload.reviewer_id)
    data = payload.model_dump(exclude={'idempotency_key'})
    if upload:
        data['upload_hash'] = sha256(upload[2]).hexdigest()
        data['filename'],data['content_type'] = upload[:2]
    command,fresh = await _claim(session,actor,'create','create',data,payload.idempotency_key)
    if not fresh:
        await _owned(session,actor,command.result['contract_id'])
        return command.result
    await _available(session,actor)
    try:
        parsed = parse_upload(*upload) if upload else parse_text(payload.text)
    except ValueError as exc:
        raise AppException(ErrorCode.BAD_REQUEST,str(exc),http_status=422) from None
    scan_status, storage_key = 'CLEAN', None
    if upload:
        scan_status = await scan_bytes(upload[2])
        storage_key = 'contracts/' + uuid4().hex + '.bin'
        path = Path(get_settings().attachment_storage_dir) / storage_key
        path.parent.mkdir(parents=True,exist_ok=True)
        await asyncio.to_thread(path.write_bytes,upload[2])
    actor = await _identity(session, actor)
    await _reviewer(session, actor,payload.reviewer_id)
    public_id = 'CON-' + uuid4().hex[:12].upper()
    thread = AgentThread(tenant_id=actor.tenant_id,user_id=actor.user_id,scene='contract',intent='contract',status='DRAFT',business_id=public_id)
    session.add(thread)
    await session.flush()
    record = ContractRecord(contract_id=public_id,thread_id=thread.id,tenant_id=actor.tenant_id,owner_id=actor.user_id,
        reviewer_id=payload.reviewer_id,title=payload.title,idempotency_key=payload.idempotency_key,node_state={})
    session.add(record)
    await session.flush()
    session.add(ContractSource(contract_id=record.id,text=parsed['text'],sha256=parsed['sha256'],paragraphs=parsed['paragraphs'],
        scan_status=scan_status,storage_key=storage_key,filename=Path(upload[0]).name if upload else None))
    await session.flush()
    return await _finish(session,record,actor,command,'create')


@business_boundary('contract', 'read')
async def get_contract(session,actor,contract_id):
    actor = await _identity(session, actor)
    return await _response(session,await _owned(session,actor,contract_id),actor)


@business_boundary('contract', 'read')
async def list_contracts(session,actor,page=1,page_size=20):
    actor = await _identity(session, actor)
    page,page_size = max(1,page), min(100,max(1,page_size))
    total = await session.scalar(select(func.count()).select_from(ContractRecord).where(*_scope(actor)))
    records = (await session.scalars(select(ContractRecord).where(*_scope(actor)).order_by(ContractRecord.updated_at.desc())
        .offset((page-1)*page_size).limit(page_size))).all()
    return dict(items=[dict(contract_id=r.contract_id,title=r.title,status=r.status,version=r.current_version,reviewer_id=r.reviewer_id) for r in records],
        total=total,page=page,page_size=page_size)


@business_boundary('contract', 'read')
async def list_versions(session,actor,contract_id):
    record = await _owned(session,actor,contract_id)
    rows = (await session.scalars(select(ContractReviewVersion).where(ContractReviewVersion.contract_id == record.id)
        .order_by(ContractReviewVersion.version))).all()
    return [dict(version=r.version,draft=r.draft,edited_by=r.edited_by,created_at=r.created_at.isoformat()) for r in rows]


@business_boundary('contract', 'read')
async def source_detail(session,actor,contract_id,source_id):
    record = await _owned(session,actor,contract_id)
    source = await _source(session,record)
    if str(source.id) != source_id:
        raise AppException(ErrorCode.NOT_FOUND,'原文不存在',http_status=404)
    return dict(source_id=source_id,text=source.text,sha256=source.sha256,paragraphs=source.paragraphs,scan_status=source.scan_status)


@business_boundary('contract', 'write')
async def command_contract(session,actor,contract_id,payload):
    actor = await _identity(session, actor)
    record = await _owned(session,actor,contract_id,lock=True)
    command,fresh = await _claim(session,actor,contract_id,payload.action,payload.model_dump(exclude={'idempotency_key'}),payload.idempotency_key)
    if not fresh:
        return command.result
    await _available(session,actor,record)
    if payload.action in {'confirm','reject'} and actor.user_id != record.reviewer_id:
        raise AppException(ErrorCode.FORBIDDEN,'只有指定复核人可提交最终决定',http_status=403)
    if payload.action not in _actions(record,actor):
        raise AppException(ErrorCode.INVALID_STATE,'当前状态不可执行该合同命令',http_status=422)
    if payload.expected_version != record.current_version:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT,'审查版本已变化，请刷新',http_status=409)
    source = await _source(session,record)
    if payload.action == 'rescan':
        if source.storage_key:
            path = Path(get_settings().attachment_storage_dir) / source.storage_key
            def read_bounded():
                with path.open('rb') as handle:
                    return handle.read(MAX_BYTES + 1)
            content = await asyncio.to_thread(read_bounded)
            if len(content) > MAX_BYTES:
                raise AppException(ErrorCode.BAD_REQUEST,'文件超限',http_status=422)
            source.scan_status = await scan_bytes(content)
        return await _finish(session,record,actor,command,payload.action)
    if payload.action in {'review','retry'}:
        if source.scan_status != 'CLEAN':
            raise AppException(ErrorCode.INVALID_STATE,'文件扫描尚未通过，请扫描或使用粘贴文本',http_status=422)
        await _reviewer(session, actor,record.reviewer_id)
        from ..graph.contract_graph import contract_graph
        parsed = dict(text=source.text,sha256=source.sha256,paragraphs=source.paragraphs)
        state = record.node_state if payload.action == 'retry' else {}
        state = {k:v for k,v in state.items() if k != '_lease'}
        state['parsed'] = parsed
        lease = str(command.command_id)
        command_record_id = command.id
        record.node_state = {**state,'_lease':lease}
        record.status,record.error_message,record.error_trace_id = 'PROCESSING',None,None
        await session.commit()
        stream = contract_graph.astream(state,stream_mode='updates').__aiter__()
        deadline = asyncio.get_running_loop().time() + 120
        analysis_failed = False
        try:
            while True:
                started = datetime.now(timezone.utc)
                # Only graph execution failures become PAUSED; persistence errors propagate.
                try:
                    async with asyncio.timeout_at(deadline):
                        event = await stream.__anext__()
                except StopAsyncIteration:
                    break
                except AppException:
                    raise
                except Exception:
                    analysis_failed = True
                    break
                name,values = next(iter(event.items()))
                record = await _owned(session,actor,contract_id,lock=True)
                await _available(session,await _identity(session, actor),record)
                if record.status != 'PROCESSING' or record.node_state.get('_lease') != lease:
                    raise AppException(ErrorCode.INVALID_STATE,'运行状态已变化',http_status=409)
                state.update(values)
                record.node_state = {**state,'_lease':lease}
                await runtime_trace_service.record_span(session,tenant_id=actor.tenant_id,trace_id=get_trace_id(),node_name=name,
                    tool_name=None,started_at=started,finished_at=datetime.now(timezone.utc),status='success',thread_id=record.thread_id)
                await session.commit()
        finally:
            await stream.aclose()
        if analysis_failed:
            await session.rollback()
            record = await _owned(session,actor,contract_id,lock=True)
            if record.node_state.get('_lease') != lease:
                raise AppException(ErrorCode.INVALID_STATE,'运行状态已变化',http_status=409) from None
            record.status = 'PAUSED'
            record.error_message = '合同分析失败，已保存完成节点，可重试剩余步骤'
            record.error_trace_id = get_trace_id()
        else:
            record = await _owned(session,actor,contract_id,lock=True)
            await _reviewer(session, await _identity(session, actor),record.reviewer_id)
            for risk in state['draft']['risks']:
                validate_evidence(parsed,risk['evidence'],missing=risk['missing'])
            next_version = (record.current_version or 0) + 1
            session.add(ContractReviewVersion(contract_id=record.id,version=next_version,draft=state['draft']))
            record.current_version, record.status = next_version,'DRAFT_READY'
            for usage in state['analysis']['usage']:
                await runtime_trace_service.record_model_usage(session,tenant_id=actor.tenant_id,trace_id=get_trace_id(),
                    provider=usage.get('provider',get_settings().llm_provider),
                    model_name=usage.get('model','contract-deepagents'),input_tokens=usage.get('prompt_tokens'),
                    output_tokens=usage.get('completion_tokens'),total_tokens=usage.get('total_tokens'))
        command = await session.get(IdempotencyRecord,command_record_id)
        return await _finish(session,record,actor,command,payload.action)
    version = await session.scalar(select(ContractReviewVersion).where(ContractReviewVersion.contract_id == record.id,
        ContractReviewVersion.version == record.current_version))
    if payload.action == 'save':
        if not payload.summary or not payload.summary.strip():
            raise AppException(ErrorCode.BAD_REQUEST,'修订摘要不能为空',http_status=422)
        draft = {**version.draft,'summary':payload.summary}
        number = record.current_version + 1
        session.add(ContractReviewVersion(contract_id=record.id,version=number,draft=draft,edited_by=actor.user_id))
        record.current_version = number
    else:
        await _reviewer(session, actor,record.reviewer_id)
        expected = {r['risk_id'] for r in version.draft['risks']}
        dispositions = payload.dispositions
        if len(dispositions) != len(expected) or {d.risk_id for d in dispositions} != expected:
            raise AppException(ErrorCode.BAD_REQUEST,'须逐项处理当前版本全部风险',http_status=422)
        if not payload.comment.strip() or any(not d.comment.strip() for d in dispositions):
            raise AppException(ErrorCode.BAD_REQUEST,'请填写人工复核意见',http_status=422)
        record.confirmation = dict(actor_id=actor.user_id,version=record.current_version,action=payload.action,
            dispositions=[d.model_dump() for d in dispositions],comment=payload.comment,at=datetime.now(timezone.utc).isoformat())
        record.status = 'CONFIRMED' if payload.action == 'confirm' else 'REJECTED'
    return await _finish(session,record,actor,command,payload.action)
