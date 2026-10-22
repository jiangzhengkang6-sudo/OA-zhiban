"""Run an isolated M1 preview; never consume application DB URLs or .env secrets."""
import asyncio
import os
from pathlib import Path
import secrets
import sys

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
PREVIEW_DB = 'oa_identity_m1_preview_test'
OUTPUT = ROOT / 'data' / 'verification' / 'm1'
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ.update({
    'ENVIRONMENT':'development', 'AUTH_PROVIDER':'builtin', 'AUTH_TENANT_ID':'m1-preview',
    'AUTH_JWT_SECRET':secrets.token_urlsafe(48), 'AUTH_COOKIE_SECURE':'false',
    'AUTH_ALLOWED_ORIGINS':'["http://127.0.0.1:5193"]',
    'DATABASE_URL':f'postgresql+asyncpg://oa:oa@localhost:5433/{PREVIEW_DB}',
    'DATABASE_SYNC_URL':f'postgresql+psycopg://oa:oa@localhost:5433/{PREVIEW_DB}',
    'CHECKPOINTER_URL':f'postgresql://oa:oa@localhost:5433/{PREVIEW_DB}',
    'LLM_PROVIDER':'mock', 'LLM_FALLBACK_PROVIDER':'none', 'EMBEDDING_PROVIDER':'mock',
    'EMBEDDING_DIM':'1536', 'OA_PROVIDER':'mock', 'CLAMD_HOST':'',
    'MOCK_STATE_FILE':str(OUTPUT / 'mock-state.json'),
    'ATTACHMENT_STORAGE_DIR':str(OUTPUT / 'attachments'),
    'KNOWLEDGE_STORAGE_DIR':str(OUTPUT / 'knowledge'),
    'AUDIT_EXPORT_STORAGE_DIR':str(OUTPUT / 'exports'),
})


async def seed():
    from sqlalchemy import select
    from app.db.session import async_session_factory, engine
    from app.models.identity import OAUser
    from app.services.identity_service import bootstrap_admin
    async with async_session_factory() as db:
        exists = await db.scalar(select(OAUser.id).where(OAUser.tenant_id=='m1-preview'))
        if not exists:
            password=secrets.token_urlsafe(24)
            await bootstrap_admin(db,'m1_admin',password,tenant_id='m1-preview')
            (OUTPUT / 'preview-login.txt').write_text(
                '仅用于独立 M1 本地预览。\n地址：http://127.0.0.1:5193\n账号：m1_admin\n密码：'+password+'\n',encoding='utf-8')
    await engine.dispose()


if __name__=='__main__':
    import psycopg
    from psycopg import sql
    from alembic import command
    from app.db.migrations import migration_config
    with psycopg.connect('postgresql://oa:oa@localhost:5433/postgres',autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s',(PREVIEW_DB,)).fetchone():
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(PREVIEW_DB)))
    command.upgrade(migration_config(),'head')
    asyncio.run(seed())
    import uvicorn
    asyncio.run(uvicorn.Server(uvicorn.Config('app.main:app',host='127.0.0.1',port=8013,loop='none')).serve())
