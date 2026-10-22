"""Revalidate formal audit references using each business service's authority."""
from uuid import UUID

from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from .authorization_service import require_permission


async def reference_allowed(db, actor, kind, identifier):
    from . import document_service, email_service, meeting_service, work_task_service
    from . import report_service, contract_service, oa_ticket_service, oa_leave_service, oa_reimbursement_service
    readers = {
        'document': document_service._owned, 'email': email_service._owned,
        'meeting': meeting_service._owned, 'work_task_batch': work_task_service._batch,
        'report': report_service._owned, 'contract': contract_service._owned,
        'ticket': oa_ticket_service.access, 'leave': oa_leave_service.applicant_access,
        'reimbursement': oa_reimbursement_service.applicant_access,
    }
    try:
        if kind in readers:
            await readers[kind](db, actor, identifier)
        elif kind == 'work_task':
            task = await work_task_service._task(db, actor, identifier)
            batch = await db.get(work_task_service.WorkTaskBatch, task.batch_id, populate_existing=True)
            await work_task_service._source_access(db, actor, batch)
        elif kind == 'approval':
            from .oa_approval_service import node_access
            await node_access(db, actor, identifier, allow_completed=True)
        elif kind in {'knowledge', 'thread'}:
            from .thread_service import can_view_thread
            from .oa_scope_service import source_allowed
            require_permission(actor, 'knowledge' if kind == 'knowledge' else 'thread', 'read')
            reference = UUID(identifier)
            thread = await db.get(AgentThread, reference, populate_existing=True)
            if thread is not None:
                return await can_view_thread(thread, actor, db)
            return kind == 'knowledge' and await source_allowed(db, actor, reference)
        elif kind == 'audit_export':
            from ..models.audit_export import AuditExport
            export = await db.get(AuditExport, UUID(identifier), populate_existing=True)
            return bool(export and export.requested_by == actor.user_id
                and (export.filters or {}).get('meeting_tenant_id') == actor.tenant_id)
        else:
            return False
    except AppException as error:
        if error.http_status in {403, 404, 409, 422, 503}:
            return False
        raise
    except ValueError:
        return False
    return True


async def audit_allowed(db, actor, row):
    resource = {'work_task_batch': 'work_task', 'audit_export': 'audit'}.get(row.resource, row.resource)
    try:
        if resource == 'system':
            if row.actor_id != actor.user_id:
                return False
        else:
            require_permission(actor, resource, 'read')
        references = {(kind, identifier) for kind, identifier in (
            (row.object_type, row.object_id), (row.source_type, row.source_id)) if identifier}
        for kind, identifier in references:
            if not await reference_allowed(db, actor, kind, identifier):
                return False
    except AppException as error:
        if error.http_status == 403:
            return False
        raise
    return True
