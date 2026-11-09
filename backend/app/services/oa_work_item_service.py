"""Read-only pending projection. Decisions stay in their original domain services."""
from ..core.config import get_settings
from .oa_access_service import builtin_actor, denied
from . import oa_approval_service, work_task_service


def permitted(actor, resource):
    return any(p['resource'] == resource and p['action'] == 'read'
        for p in actor.data_scope.get('permissions', []))


async def pending(db, actor, *, source=None, page=1, page_size=20):
    actor = await builtin_actor(db, actor)
    ai_enabled = get_settings().ai_enabled
    if not permitted(actor, 'approval') and not (ai_enabled and permitted(actor, 'work_task')):
        raise denied()
    items = []
    if source in {None, 'approval'} and permitted(actor, 'approval'):
        for row in await oa_approval_service.list_items(db, actor, 'pending'):
            items.append(dict(id='approval:' + row['node_id'], source='approval',
                title=('代批 · ' if row.get('is_delegated') else '') + ('报销审批 ' if row['scene'] == 'reimbursement' else '请假审批 ') + row['business_no'],
                business_id=row['business_no'], state=row['seat_state'], due_at=row['due_at'],
                href='/oa/approvals?node_id=' + row['node_id']))
    if ai_enabled and source in {None, 'work_task'} and permitted(actor, 'work_task'):
        cursor = 1
        while True:
            batch = await work_task_service.list_tasks(db, actor, page=cursor, page_size=100)
            for row in batch.items:
                if row.assignee_id != actor.user_id or row.status not in {'OPEN', 'IN_PROGRESS'}:
                    continue
                items.append(dict(id='work_task:' + row.task_id, source='work_task', title=row.title,
                    business_id=row.task_id, state=row.status, due_at=row.due_at.isoformat(),
                    href='/work-tasks/' + row.task_id))
            if cursor * batch.page_size >= batch.total:
                break
            cursor += 1
    items.sort(key=lambda row: (row['due_at'] is None, row['due_at'] or '', row['id']))
    start = (page - 1) * page_size
    return dict(items=items[start:start + page_size], total=len(items), page=page, page_size=page_size)
