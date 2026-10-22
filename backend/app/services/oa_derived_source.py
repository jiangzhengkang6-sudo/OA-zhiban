"""Resolve formal sources for derived work without legacy table fallback."""
from hashlib import sha256
import json

from sqlalchemy import or_, select

from ..models.oa_ticket import OATicket
from ..models.oa_workflow import OAWorkflowInstance, OAWorkflowNode
from . import oa_ticket_service as tickets, oa_approval_service as approvals
from .oa_access_service import denied, invalid, revision_conflict
from .oa_workflow_subject import subject_models, resolve_subject
from ..core.errors import AppException


async def ticket_source(db, actor, identifier, version=None):
    rows = (await db.scalars(select(OATicket).where(OATicket.tenant_id == actor.tenant_id,
        or_(OATicket.id == identifier, OATicket.business_no == identifier)))).all()
    if len(rows) != 1:
        raise denied()
    _, row = await tickets.access(db, actor, rows[0].id)
    if version is not None and row.revision != version:
        raise revision_conflict()
    content = json.dumps(dict(工单号=row.business_no, 摘要=row.summary, 状态=row.state,
        处理说明=row.resolution_note, 合并请求=row.merged_requests), ensure_ascii=False, sort_keys=True)
    return _snapshot('ticket', identifier, str(row.revision), row.business_no, content)


async def approval_source(db, actor, identifier, version=None):
    instance = await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id == actor.tenant_id,
        OAWorkflowInstance.id == identifier))
    if instance is None:
        matches = []
        for scene in ('leave', 'reimbursement'):
            model, version_model, key, association = subject_models(scene)
            query = select(OAWorkflowInstance).join(version_model,
                (getattr(OAWorkflowInstance, association) == version_model.id) &
                (OAWorkflowInstance.tenant_id == version_model.tenant_id)).join(model,
                (getattr(version_model, key) == model.id) & (version_model.tenant_id == model.tenant_id)).where(
                model.tenant_id == actor.tenant_id, or_(model.id == identifier, model.business_no == identifier),
                OAWorkflowInstance.scene == scene, version_model.version == (version if version is not None else model.submission_version))
            matches.extend((await db.scalars(query)).all())
        if len(matches) != 1:
            raise denied()
        instance = matches[0]
    subject = await resolve_subject(db, actor, instance)
    # Owners and departmental business readers use the current source scope.
    # A completed approver must still hold the matching, eligible decision seat.
    try:
        if subject.scene == 'leave':
            from .oa_leave_service import applicant_access
        else:
            from .oa_reimbursement_service import applicant_access
        await applicant_access(db, actor, subject.object_id)
    except AppException as error:
        if error.http_status != 403:
            raise
        nodes = (await db.scalars(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id == actor.tenant_id,
            OAWorkflowNode.instance_id == instance.id))).all()
        for node in nodes:
            try:
                await approvals.node_access(db, actor, node.id, allow_completed=True)
                break
            except AppException as seat_error:
                if seat_error.http_status != 403:
                    raise
        else:
            raise denied()
    if instance.state not in {'APPROVED', 'REJECTED', 'CANCELLED'}:
        raise invalid('审批结果尚未结束')
    if version is not None and subject.submission_version != version:
        raise revision_conflict()
    content = f'审批单：{subject.row.business_no}；审批结果：{instance.state}；提交版本：{subject.submission_version}'
    return _snapshot('approval', identifier, str(subject.submission_version), subject.row.business_no, content)


def _snapshot(kind, identifier, version, title, content):
    if len(content) > 30000:
        raise invalid('来源超过 30000 字符限制')
    return dict(ref=f'{kind}:{identifier}:{version}', source_type=kind, source_id=identifier,
        version=version, title=title, content=content, content_hash=sha256(content.encode()).hexdigest(), action_items=[])
