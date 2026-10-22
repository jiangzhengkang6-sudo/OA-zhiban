"""Start the isolated M2 manual OA preview; never reuse M1/P3 state."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
PREVIEW_DB = 'oa_workflow_m2_preview_test'
OUTPUT = ROOT / 'data' / 'verification' / 'm2'
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ.update({
    'ENVIRONMENT': 'development', 'AI_ENABLED': 'false', 'AUTH_PROVIDER': 'builtin',
    'AUTH_TENANT_ID': 'm2-preview', 'AUTH_JWT_SECRET': secrets.token_urlsafe(48),
    'AUTH_COOKIE_SECURE': 'false', 'AUTH_ALLOWED_ORIGINS': '["http://127.0.0.1:5194"]',
    'DATABASE_URL': f'postgresql+asyncpg://oa:oa@localhost:5433/{PREVIEW_DB}',
    'DATABASE_SYNC_URL': f'postgresql+psycopg://oa:oa@localhost:5433/{PREVIEW_DB}',
    'CHECKPOINTER_URL': f'postgresql://oa:oa@localhost:5433/{PREVIEW_DB}',
    'LLM_PROVIDER': 'mock', 'LLM_FALLBACK_PROVIDER': 'none', 'EMBEDDING_PROVIDER': 'mock',
    'OA_PROVIDER': 'mock', 'CLAMD_HOST': '', 'MOCK_STATE_FILE': str(OUTPUT / 'mock-state.json'),
    'ATTACHMENT_STORAGE_DIR': str(OUTPUT / 'attachments'), 'KNOWLEDGE_STORAGE_DIR': str(OUTPUT / 'knowledge'),
    'AUDIT_EXPORT_STORAGE_DIR': str(OUTPUT / 'exports'),
})


async def seed():
    from sqlalchemy import select
    from app.db.session import async_session_factory, engine
    from app.models.identity import OADepartment, OAMembership, OAPermission, OARole, OARolePermission, OAUser, OAUserRole
    from app.services.credential_service import hash_password
    from app.services.identity_service import bootstrap_admin, current_identity
    from app.services import oa_workflow_service as workflows, oa_balance_service as balances
    from app.schemas.oa_workflow import WorkflowSave, PublishWorkflow
    from app.schemas.oa_leave import BalanceAdjustment
    from app.models.oa_workflow import OAWorkflowDefinition
    from app.models.oa_leave import OALeaveBalance

    tenant = 'm2-preview'
    async with async_session_factory() as db:
        admin = await db.scalar(select(OAUser).where(OAUser.tenant_id == tenant, OAUser.normalized_username == 'm2_admin'))
        accounts = {}
        for username, name in [('m2_admin', '验收管理员'), ('m2_manager', '审批经理'), ('m2_reviewer', '复核专员'), ('m2_employee', '申请员工')]:
            password = secrets.token_urlsafe(24)
            user = await db.scalar(select(OAUser).where(OAUser.tenant_id == tenant, OAUser.normalized_username == username))
            if username == 'm2_admin' and user is None:
                await bootstrap_admin(db, username, password, tenant_id=tenant)
                user = await db.scalar(select(OAUser).where(OAUser.tenant_id == tenant, OAUser.normalized_username == username))
            if user is None:
                user = OAUser(tenant_id=tenant, normalized_username=username, display_name=name, password_hash='pending')
                db.add(user)
            user.password_hash = await asyncio.to_thread(hash_password, password)
            user.auth_version = (user.auth_version or 1) + 1
            user.status = 'active'
            user.failed_attempts = 0
            user.locked_until = None
            await db.flush()
            accounts[username] = {'username': username, 'password': password, 'id': user.id}
        admin = await db.get(OAUser, accounts['m2_admin']['id'])
        manager = await db.get(OAUser, accounts['m2_manager']['id'])
        department = await db.scalar(select(OADepartment).where(OADepartment.tenant_id == tenant, OADepartment.name == 'M2 验收部门'))
        if department is None:
            department = OADepartment(tenant_id=tenant, name='M2 验收部门'); db.add(department); await db.flush()
        for account in accounts.values():
            membership = await db.get(OAMembership, (tenant, account['id']))
            if membership is None:
                db.add(OAMembership(tenant_id=tenant, user_id=account['id'], department_id=department.id, manager_id=manager.id if account['username']=='m2_employee' else None))
        for code, name, members, resources, scope in [
            ('m2_manager','M2 审批管理',['m2_admin','m2_manager','m2_reviewer'],['leave','approval','workflow','leave_balance','workflow_admin'],'department'),
            ('m2_employee','M2 申请员工',['m2_employee'],['leave','leave_balance'],'self'),
        ]:
            role = await db.scalar(select(OARole).where(OARole.tenant_id==tenant,OARole.code==code))
            if role is None:
                role=OARole(tenant_id=tenant,code=code,name=name);db.add(role);await db.flush()
            for username in members:
                if await db.get(OAUserRole,(tenant,accounts[username]['id'],role.id)) is None:
                    db.add(OAUserRole(tenant_id=tenant,user_id=accounts[username]['id'],role_id=role.id))
            for resource in resources:
                for action in ('read','write'):
                    permission=await db.scalar(select(OAPermission).where(OAPermission.resource==resource,OAPermission.action==action,OAPermission.scope==scope))
                    if permission is None:
                        permission=OAPermission(resource=resource,action=action,scope=scope);db.add(permission);await db.flush()
                    if await db.get(OARolePermission,(tenant,role.id,permission.id)) is None:
                        db.add(OARolePermission(tenant_id=tenant,role_id=role.id,permission_id=permission.id))
        await db.commit()
        actor=await current_identity(db,admin)
        for mode,name in [('single','普通请假'),('all','会签请假'),('any','或签请假')]:
            existing=await db.scalar(select(OAWorkflowDefinition).where(OAWorkflowDefinition.tenant_id==tenant,OAWorkflowDefinition.code=='preview_'+mode))
            if existing is None:
                definition={'schema_version':1,'scene':'leave','entry_id':'review','form':{'leave_types':['annual','sick'],'reason_max_length':2000},'rules':{'timeout_hours':48,'required_attachments':[],'calendar':'inclusive_days'},'nodes':[
                    {'id':'review','kind':'approval','mode':mode,'selector':{'kind':'users','user_ids':[accounts[u]['id'] for u in (['m2_manager'] if mode=='single' else ['m2_manager','m2_reviewer'])]},'next_id':'end'}, {'id':'end','kind':'end'}]}
                saved=await workflows.save_definition(db,actor,WorkflowSave(operation_id='preview-save-'+mode,department_id=department.id,code='preview_'+mode,name=name,definition=definition))
                await workflows.publish_definition(db,actor,saved['id'],PublishWorkflow(operation_id='preview-publish-'+mode,expected_revision=1))
                await db.commit()
        for account in accounts.values():
            for leave_type in ('annual','sick'):
                for year in (2026,2027):
                    existing=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.tenant_id==tenant,OALeaveBalance.user_id==account['id'],OALeaveBalance.year==year,OALeaveBalance.leave_type==leave_type))
                    if existing is None:
                        await balances.adjust(db,actor,BalanceAdjustment(operation_id=f"preview-balance-{account['id']}-{leave_type}-{year}",expected_revision=0,user_id=account['id'],leave_type=leave_type,year=year,total=365,reason='独立预览验收额度'))
                        await db.commit()
        (OUTPUT / 'preview-credentials.json').write_text(json.dumps(accounts,ensure_ascii=False,indent=2),encoding='utf-8')
        lines=['仅用于独立 M2 本地预览。','地址：http://127.0.0.1:5194']
        for account in accounts.values():
            lines.extend([f"账号：{account['username']}",f"密码：{account['password']}"])
        (OUTPUT / 'preview-login.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    await engine.dispose()


if __name__ == '__main__':
    import psycopg
    from psycopg import sql
    from alembic import command
    from app.db.migrations import migration_config
    with psycopg.connect('postgresql://oa:oa@localhost:5433/postgres', autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', (PREVIEW_DB,)).fetchone():
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(PREVIEW_DB)))
    command.upgrade(migration_config(), 'head')
    asyncio.run(seed(), loop_factory=asyncio.SelectorEventLoop)
    if '--seed-only' in sys.argv:
        sys.exit(0)
    import uvicorn
    asyncio.run(uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=8014, loop='none')).serve(), loop_factory=asyncio.SelectorEventLoop)
