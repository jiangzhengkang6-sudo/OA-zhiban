"""Built-in leave application drafts, immutable versions and precheck."""

import asyncio
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.oa_adapter import LeaveCase
from ..adapters.factory import get_adapter
from ..core.context import CurrentUser
from ..core.errors import AppException, ErrorCode
from ..models.leave_application import LeaveApplication
from ..models.leave_application_version import LeaveApplicationVersion
from ..models.agent_thread import AgentThread
from ..models.approval_decision import ApprovalDecision
from ..repositories import thread_repo
from ..services import approval_service, audit_service
from . import leave_attachment_service
from ..tools import leave_tools
from ..providers.builtin import BuiltinLeaveProvider, paused
from ..schemas.leave_application import (LeaveApplicationCreate, LeaveApplicationPatch,
                                         LeaveApplicationPage, LeaveApplicationResponse,
                                         LeaveVersionResponse)


def _fields(payload) -> dict:
    raw = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else dict(payload)
    for key, value in list(raw.items()):
        if hasattr(value, "isoformat"):
            raw[key] = value.isoformat()
    return raw


def _response(application: LeaveApplication, precheck=None) -> LeaveApplicationResponse:
    return LeaveApplicationResponse(application_id=str(application.id), thread_id=str(application.thread_id) if application.thread_id else None, business_id=application.business_id,
                                    user_id=application.user_id, status=application.status,
                                    version=application.current_version, fields=application.latest_fields,
                                    precheck=precheck, created_at=application.created_at,
                                    updated_at=application.updated_at)


async def _get_owned(session: AsyncSession, application_id: UUID, actor: CurrentUser) -> LeaveApplication:
    application = (await session.scalars(select(LeaveApplication).where(
        LeaveApplication.id == application_id).with_for_update())).one_or_none()
    if application is None:
        raise AppException(ErrorCode.NOT_FOUND, "请假申请不存在", http_status=404)
    if application.tenant_id != actor.tenant_id or application.user_id != actor.user_id:
        raise AppException(ErrorCode.FORBIDDEN, "无权访问该请假申请", http_status=403)
    return application


async def create_draft(session: AsyncSession, actor: CurrentUser, payload: LeaveApplicationCreate):
    fields = _fields(payload)
    if fields.get('attachments'):
        raise AppException(ErrorCode.BAD_REQUEST, '请先保存草稿，再上传附件', http_status=400)
    application = LeaveApplication(tenant_id=actor.tenant_id, user_id=actor.user_id,
                                   business_id=f"LA-{uuid4().hex[:12].upper()}", status="DRAFT",
                                   current_version=0, latest_fields=fields)
    session.add(application)
    await session.flush()
    await session.refresh(application)
    return _response(application)


async def get_application(session: AsyncSession, actor: CurrentUser, application_id: UUID):
    application = await _get_owned(session, application_id, actor)
    version = (await session.scalars(select(LeaveApplicationVersion).where(
        LeaveApplicationVersion.application_id == application.id,
        LeaveApplicationVersion.version == application.current_version))).one_or_none()
    return _response(application, version.precheck_result if version else None)


async def list_applications(session: AsyncSession, actor: CurrentUser, *, page: int = 1,
                            page_size: int = 20, status: str | None = None):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    conditions = [LeaveApplication.tenant_id == actor.tenant_id,
                 LeaveApplication.user_id == actor.user_id]
    if status:
        conditions.append(LeaveApplication.status == status)
    total = await session.scalar(select(func.count()).select_from(
        select(LeaveApplication.id).where(*conditions).subquery())) or 0
    rows = (await session.scalars(select(LeaveApplication).where(*conditions)
                                  .order_by(LeaveApplication.updated_at.desc(),
                                            LeaveApplication.created_at.desc())
                                  .offset((page - 1) * page_size).limit(page_size))).all()
    return LeaveApplicationPage(items=[_response(item) for item in rows], total=total,
                                page=page, page_size=page_size)


async def patch_draft(session: AsyncSession, actor: CurrentUser, application_id: UUID, payload: LeaveApplicationPatch):
    application = await _get_owned(session, application_id, actor)
    await _validate_precheck_retry(session, application)
    if application.status not in {"DRAFT", "NEEDS_FIX", "REJECTED", "PAUSED"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前状态不可编辑", http_status=422)
    fields = _fields(payload)
    if 'attachments' in fields:
        await leave_attachment_service.resolve_refs(session, application.id, fields['attachments'])
    application.latest_fields = {**application.latest_fields, **fields}
    application.status = "DRAFT"
    await session.flush()
    await session.refresh(application)
    return _response(application)


async def submit(session: AsyncSession, actor: CurrentUser, application_id: UUID):
    application = await _get_owned(session, application_id, actor)
    await _validate_precheck_retry(session, application)
    if application.status not in {"DRAFT", "NEEDS_FIX", "REJECTED", "PAUSED"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前状态不可提交", http_status=422)
    version_no = application.current_version + 1
    fields = application.latest_fields
    try:
        case = LeaveCase(business_id=application.business_id, user_id=application.user_id, **fields)
    except Exception as exc:
        raise AppException(ErrorCode.BAD_REQUEST, "请假字段无法验证", http_status=400) from exc
    await _lock_owner(session, application)
    precheck = await BuiltinLeaveProvider().precheck(case, session=session, application_id=application.id)
    route = None
    if precheck['passed']:
        try:
            response = await asyncio.wait_for(asyncio.to_thread(
                get_adapter().get_approval_route, application.user_id, case), timeout=10)
            route = response.model_dump()
            if route.get('conflict') or not route.get('nodes'):
                raise ValueError('组织路由不可判定')
        except Exception:
            precheck = paused(precheck['items'], 'route')
    status = 'SUBMITTED' if precheck['passed'] else precheck.get('status', 'NEEDS_FIX')
    thread = None
    if precheck["passed"]:
        thread = await session.get(AgentThread, application.thread_id) if application.thread_id else None
        if thread is None:
            thread = await thread_repo.create_thread(
                session, user_id=application.user_id, tenant_id=application.tenant_id,
                scene="leave", business_id=application.business_id, status="WAITING_HUMAN")
        thread.status = "WAITING_HUMAN"
        thread.error_code = None
        thread.error_msg = None
        await approval_service.ensure_instance(
            session, thread.id, application.tenant_id, application.business_id,
            route, version=version_no
        )
        application.thread_id = thread.id
    version = LeaveApplicationVersion(application_id=application.id, version=version_no, fields=fields,
                                      precheck_result=precheck, status=status)
    session.add(version)
    application.current_version = version_no
    application.rule_version = precheck["rule_version"]
    application.status = status
    if application.thread_id and not precheck["passed"]:
        existing_thread = await session.get(AgentThread, application.thread_id)
        existing_thread.status = status
        existing_thread.error_code = precheck.get('error', {}).get('code')
        existing_thread.error_msg = precheck.get('error', {}).get('msg')
    await audit_service.audit(session, 'precheck_result', actor_id=actor.user_id,
        business_id=application.business_id, target_type='leave_application', target_id=str(application.id),
        output_summary={'passed': precheck['passed'], 'rule_version': precheck['rule_version'], 'status': status},
        error_code=precheck.get('error', {}).get('code'), result='paused' if status == 'PAUSED' else 'success')
    await session.flush()
    await session.refresh(application)
    return _response(application, precheck)


async def _lock_owner(session, application):
    # All local submit/edit/approval transactions for an employee share this transaction lock.
    import json
    key = json.dumps([application.tenant_id, application.user_id], separators=(',', ':'))
    await session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:owner_key, 0))'),
                          {'owner_key': key})


async def _validate_precheck_retry(session, application):
    if application.status != 'PAUSED':
        return
    version = await session.scalar(select(LeaveApplicationVersion).where(
        LeaveApplicationVersion.application_id == application.id,
        LeaveApplicationVersion.version == application.current_version))
    instance = await approval_service.get_instance(session, application.thread_id) if application.thread_id else None
    if (not version or (version.precheck_result or {}).get('status') != 'PAUSED'
            or instance and instance.status not in {'NEEDS_FIX', 'REJECTED'}):
        raise AppException(ErrorCode.INVALID_STATE, '当前暂停申请需先核对审批写入结果，不能修改或重提', http_status=409)


async def list_versions(session: AsyncSession, actor: CurrentUser, application_id: UUID):
    application = await _get_owned(session, application_id, actor)
    versions = (await session.scalars(select(LeaveApplicationVersion).where(
        LeaveApplicationVersion.application_id == application.id).order_by(LeaveApplicationVersion.version))).all()
    return [LeaveVersionResponse(version=item.version, status=item.status, fields=item.fields,
                                 precheck=item.precheck_result, created_at=item.created_at) for item in versions]


async def decide(session: AsyncSession, actor: CurrentUser, application_id: UUID,
                 action: str, comment: str, edited_data: dict | None, idempotency_key: str):
    """Record a built-in approval decision against the persisted task projection."""
    application = (await session.scalars(select(LeaveApplication).where(
        LeaveApplication.id == application_id).with_for_update())).one_or_none()
    if application is None or application.tenant_id != actor.tenant_id:
        raise AppException(ErrorCode.NOT_FOUND, "请假申请不存在", http_status=404)
    if not application.thread_id:
        raise AppException(ErrorCode.INVALID_STATE, "请假申请尚未进入审批", http_status=409)
    await _lock_owner(session, application)
    thread = await session.get(AgentThread, application.thread_id)
    if thread is None:
        raise AppException(ErrorCode.INVALID_STATE, "请假审批任务不存在", http_status=409)
    instance = await approval_service.get_instance(session, thread.id)
    previous = (await session.scalars(select(ApprovalDecision).where(
        ApprovalDecision.instance_id == instance.id,
        ApprovalDecision.idempotency_key == idempotency_key))).one_or_none() if instance else None
    if action == 'approve' and not previous:
        if instance is None or instance.status != 'ACTIVE' or application.status != 'SUBMITTED':
            raise AppException(ErrorCode.INVALID_STATE, '当前审批实例不可处理', http_status=409)
        node = await approval_service.active_node(session, thread.id)
        if node is None or node.approver_id != actor.user_id:
            raise AppException(ErrorCode.FORBIDDEN, '当前用户不是本级审批人', http_status=403)
        case = LeaveCase(business_id=application.business_id, user_id=application.user_id,
                         **application.latest_fields)
        precheck = await BuiltinLeaveProvider().precheck(case, session=session, application_id=application.id)
        if not precheck['passed']:
            application.current_version += 1
            application.rule_version = precheck['rule_version']
            application.status = precheck.get('status', 'NEEDS_FIX')
            session.add(LeaveApplicationVersion(application_id=application.id,
                version=application.current_version, fields=application.latest_fields,
                precheck_result=precheck, status=application.status))
            instance.status = 'NEEDS_FIX'
            thread.status = application.status
            thread.error_code = precheck.get('error', {}).get('code')
            thread.error_msg = precheck.get('error', {}).get('msg')
            await audit_service.audit(session, 'precheck_result', actor_id=actor.user_id,
                thread_id=thread.id, business_id=application.business_id,
                result='paused' if application.status == 'PAUSED' else 'failed',
                error_code=thread.error_code, output_summary={'status': application.status, 'passed': False})
            await session.flush()
            return {'application_id': str(application.id), 'thread_id': str(thread.id),
                    'status': thread.status, 'next_action': 'paused' if thread.status == 'PAUSED' else 'needs_fix'}
    result = await approval_service.record_decision(
        session, thread.id, actor.user_id, action, comment or "", edited_data, idempotency_key
    )
    if previous:
        return {"application_id": str(application.id), "thread_id": str(thread.id),
                "status": thread.status, "next_action": result}
    if action == "edit":
        fields = {**application.latest_fields, **(edited_data or {})}
        case = LeaveCase(business_id=application.business_id, user_id=application.user_id, **fields)
        precheck = await BuiltinLeaveProvider().precheck(case, session=session, application_id=application.id)
        application.current_version += 1
        application.latest_fields = fields
        application.rule_version = precheck["rule_version"]
        application.status = 'SUBMITTED' if precheck['passed'] else precheck.get('status', 'NEEDS_FIX')
        session.add(LeaveApplicationVersion(application_id=application.id,
            version=application.current_version, fields=fields, precheck_result=precheck,
            status=application.status))
        instance.version = application.current_version
        instance.status = "ACTIVE" if precheck["passed"] else "NEEDS_FIX"
        thread.status = 'WAITING_HUMAN' if precheck['passed'] else application.status
        thread.error_code = precheck.get('error', {}).get('code')
        thread.error_msg = precheck.get('error', {}).get('msg')
        await audit_service.audit(session, 'precheck_result', actor_id=actor.user_id,
            thread_id=thread.id, business_id=application.business_id,
            result='paused' if application.status == 'PAUSED' else 'success',
            error_code=thread.error_code, output_summary={'status': application.status, 'passed': precheck['passed']})
        await session.flush()
        return {"application_id": str(application.id), "thread_id": str(thread.id),
                "status": thread.status, "next_action": 'human' if precheck['passed'] else 'paused' if thread.status == 'PAUSED' else 'needs_fix'}
    if result == "rejected":
        application.status = "REJECTED"
        thread.status = "REJECTED"
    elif result == "pending_write":
        await approval_service.finalize_approval(session, thread.id, f"builtin-{thread.id}")
        application.status = "APPROVED"
        thread.status = "APPROVED"
    else:
        application.status = "SUBMITTED"
        thread.status = "WAITING_HUMAN"
    await session.flush()
    return {"application_id": str(application.id), "thread_id": str(thread.id),
            "status": thread.status, "next_action": result}
