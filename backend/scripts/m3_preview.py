"""Start the isolated M3 formal OA preview on the approved preview database."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
PREVIEW_DB = 'oa_business_m3_preview_test'
DATABASES = frozenset({'oa_business_m3_test', PREVIEW_DB})
OUTPUT = ROOT / 'data' / 'verification' / 'm3'
PREVIEW_PORT = 8015
FRONTEND_PORT = 5195


def preview_address():
    from sqlalchemy.engine import make_url
    if PREVIEW_DB not in DATABASES:
        raise RuntimeError('M3 preview database is outside the approved allowlist')
    address = make_url(os.environ.get('M3_DATABASE_SERVER_URL', 'postgresql://oa:oa@localhost:5433/postgres'))
    if address.get_backend_name() != 'postgresql':
        raise RuntimeError('M3 preview requires a PostgreSQL server')
    return address


def configure():
    from app.db.safety import validate_test_targets
    address = preview_address()
    urls = [address.set(drivername=driver, database=PREVIEW_DB).render_as_string(hide_password=False)
            for driver in ('postgresql+asyncpg', 'postgresql+psycopg', 'postgresql')]
    validate_test_targets('test', True, *urls)
    os.environ.update({
        'ENVIRONMENT': 'development',
        'AI_ENABLED': 'false',
        'AUTH_PROVIDER': 'builtin',
        'AUTH_TENANT_ID': 'm3-preview',
        'AUTH_JWT_SECRET': secrets.token_urlsafe(48),
        'AUTH_COOKIE_SECURE': 'false',
        'AUTH_ALLOWED_ORIGINS': f'["http://127.0.0.1:{FRONTEND_PORT}","http://localhost:{FRONTEND_PORT}"]',
        **dict(zip(('DATABASE_URL', 'DATABASE_SYNC_URL', 'CHECKPOINTER_URL'), urls)),
        'LLM_PROVIDER': 'mock',
        'LLM_FALLBACK_PROVIDER': 'none',
        'EMBEDDING_PROVIDER': 'mock',
        'EMBEDDING_DIM': '1536',
        'OA_PROVIDER': 'builtin',
        'SMTP_ENABLED': 'false',
        'SMTP_HOST': '127.0.0.1',
        'SMTP_USERNAME': '',
        'SMTP_PASSWORD': '',
        'CLAMD_HOST': '',
        'MOCK_STATE_FILE': str(OUTPUT / 'preview-mock-state.json'),
        'ATTACHMENT_STORAGE_DIR': str(OUTPUT / 'preview-attachments'),
        'KNOWLEDGE_STORAGE_DIR': str(OUTPUT / 'preview-knowledge'),
        'AUDIT_EXPORT_STORAGE_DIR': str(OUTPUT / 'preview-exports'),
        'NOTIFICATION_APP_URL': f'http://127.0.0.1:{FRONTEND_PORT}/oa/notifications',
        'OA_BACKEND_PORT': str(PREVIEW_PORT),
    })
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'preview-env.json').write_text(json.dumps({
        'database': PREVIEW_DB, 'backend': f'http://127.0.0.1:{PREVIEW_PORT}',
        'frontend': f'http://127.0.0.1:{FRONTEND_PORT}', 'ai_enabled': False,
        'llm_provider': 'mock', 'embedding_provider': 'mock', 'smtp_enabled': False,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


def ensure_database():
    import psycopg
    from psycopg import sql
    base = preview_address().set(drivername='postgresql', database='postgres').render_as_string(hide_password=False)
    with psycopg.connect(base, autocommit=True) as connection:
        if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (PREVIEW_DB,)).fetchone():
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(PREVIEW_DB)))


async def seed():
    from sqlalchemy import select
    from app.db.session import async_session_factory, engine
    from app.models.identity import OADepartment, OAMembership, OAPermission, OARole, OARolePermission, OAUser, OAUserRole
    from app.services.credential_service import hash_password
    from app.services.identity_service import bootstrap_admin, current_identity
    from app.models.oa_workflow import OAWorkflowDefinition
    from app.models.oa_ticket import OATicketAssignmentRule
    from app.schemas.oa_workflow import WorkflowSave, PublishWorkflow
    from app.schemas.oa_ticket import TicketRuleSave
    from app.services import oa_workflow_service as workflows, oa_ticket_service as tickets

    tenant = 'm3-preview'
    username = 'm3_admin'
    password = secrets.token_urlsafe(24)
    async with async_session_factory() as db:
        user = await db.scalar(select(OAUser).where(OAUser.tenant_id == tenant, OAUser.normalized_username == username))
        role = await db.scalar(select(OARole).where(OARole.tenant_id == tenant, OARole.code == 'admin'))
        if user is None and role is None:
            user = await bootstrap_admin(db, username, password, tenant_id=tenant)
            role = await db.scalar(select(OARole).where(OARole.tenant_id == tenant, OARole.code == 'admin'))
        if user is None or role is None:
            raise RuntimeError('M3 preview identity seed is incomplete; repair only the approved preview database')
        user.password_hash = await asyncio.to_thread(hash_password, password)
        user.auth_version = (user.auth_version or 1) + 1
        user.status = 'active'
        user.failed_attempts = 0
        user.locked_until = None
        department = await db.scalar(select(OADepartment).where(OADepartment.tenant_id == tenant, OADepartment.name == 'M3 预览部门'))
        if department is None:
            department = OADepartment(tenant_id=tenant, name='M3 预览部门')
            db.add(department)
            await db.flush()
        if await db.get(OAMembership, (tenant, user.id)) is None:
            db.add(OAMembership(tenant_id=tenant, user_id=user.id, department_id=department.id))
        resources = ('leave', 'approval', 'workflow', 'leave_balance', 'workflow_admin', 'reimbursement', 'ticket', 'ticket_handle', 'ticket_admin', 'notification', 'notification_admin')
        for resource in resources:
            for action in ('read', 'write'):
                permission = await db.scalar(select(OAPermission).where(OAPermission.resource == resource, OAPermission.action == action, OAPermission.scope == 'department'))
                if permission is None:
                    permission = OAPermission(resource=resource, action=action, scope='department')
                    db.add(permission)
                    await db.flush()
                if await db.get(OARolePermission, (tenant, role.id, permission.id)) is None:
                    db.add(OARolePermission(tenant_id=tenant, role_id=role.id, permission_id=permission.id))
        # The employee has explicit self grants; it cannot inherit manager access.
        employee_password = secrets.token_urlsafe(24)
        employee = await db.scalar(select(OAUser).where(OAUser.tenant_id == tenant, OAUser.normalized_username == 'm3_employee'))
        if employee is None:
            employee = OAUser(tenant_id=tenant, normalized_username='m3_employee', display_name='申请员工', password_hash='pending')
            db.add(employee)
        employee.password_hash = await asyncio.to_thread(hash_password, employee_password)
        employee.auth_version = (employee.auth_version or 1) + 1
        employee.status = 'active'
        employee.failed_attempts = 0
        employee.locked_until = None
        await db.flush()
        if await db.get(OAMembership, (tenant, employee.id)) is None:
            db.add(OAMembership(tenant_id=tenant, user_id=employee.id, department_id=department.id, manager_id=user.id))
        employee_role = await db.scalar(select(OARole).where(OARole.tenant_id == tenant, OARole.code == 'm3_employee'))
        if employee_role is None:
            employee_role = OARole(tenant_id=tenant, code='m3_employee', name='M3 申请员工')
            db.add(employee_role)
            await db.flush()
        if await db.get(OAUserRole, (tenant, employee.id, employee_role.id)) is None:
            db.add(OAUserRole(tenant_id=tenant, user_id=employee.id, role_id=employee_role.id))
        for resource in ('reimbursement', 'ticket', 'notification'):
            for action in ('read', 'write'):
                permission = await db.scalar(select(OAPermission).where(OAPermission.resource == resource, OAPermission.action == action, OAPermission.scope == 'self'))
                if permission is None:
                    permission = OAPermission(resource=resource, action=action, scope='self')
                    db.add(permission)
                    await db.flush()
                if await db.get(OARolePermission, (tenant, employee_role.id, permission.id)) is None:
                    db.add(OARolePermission(tenant_id=tenant, role_id=employee_role.id, permission_id=permission.id))
        await db.commit()
        actor = await current_identity(db, user)
        existing = await db.scalar(select(OAWorkflowDefinition).where(OAWorkflowDefinition.tenant_id == tenant, OAWorkflowDefinition.code == 'm3_preview_reimbursement'))
        if existing is None:
            definition = dict(schema_version=1, scene='reimbursement', entry_id='review',
                form=dict(categories=['交通', '差旅', '办公', '招待', '其他']), rules=dict(timeout_hours=48),
                nodes=[dict(id='review', kind='approval', mode='single', selector=dict(kind='manager', levels=1), next_id='end'), dict(id='end', kind='end')])
            saved = await workflows.save_definition(db, actor, WorkflowSave(operation_id='preview-workflow', department_id=department.id, code='m3_preview_reimbursement', name='日常费用报销', definition=definition))
            await workflows.publish_definition(db, actor, saved['id'], PublishWorkflow(operation_id='preview-publish', expected_revision=1))
            await db.commit()
        rule = await db.scalar(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id == tenant, OATicketAssignmentRule.code == 'preview_default'))
        if rule is None:
            await tickets.save_rule(db, actor, TicketRuleSave(operation_id='preview-ticket-rule', department_id=department.id, code='preview_default', queue='服务台', assignee_id=user.id))
            await db.commit()
        credentials = {'username': username, 'password': password,
            'employee': {'username': 'm3_employee', 'password': employee_password}}
        (OUTPUT / 'preview-credentials.json').write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding='utf-8')
        (OUTPUT / 'preview-login.txt').write_text(f'仅用于独立 M3 本地预览；每次启动轮换密码。\n地址：http://127.0.0.1:{FRONTEND_PORT}\n管理员：{username}\n密码：{password}\n申请员工：m3_employee\n密码：{employee_password}\nAI、真实 SMTP 和文件扫描均未启用，未扫描发票不可提交。\n', encoding='utf-8')
    await engine.dispose()


if __name__ == '__main__':
    configure()
    ensure_database()
    from alembic import command
    from app.db.migrations import migration_config
    command.upgrade(migration_config(), 'head')
    asyncio.run(seed(), loop_factory=asyncio.SelectorEventLoop)
    if '--seed-only' in sys.argv:
        sys.exit(0)
    import uvicorn
    asyncio.run(uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=PREVIEW_PORT, loop='none')).serve(), loop_factory=asyncio.SelectorEventLoop)
