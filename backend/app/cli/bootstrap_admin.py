import argparse
import asyncio
import getpass
from ..core.config import get_settings
from ..db.session import async_session_factory, engine
from ..services.identity_service import bootstrap_admin


async def run(username, password):
    try:
        async with async_session_factory() as db:
            await bootstrap_admin(db, username, password, tenant_id=get_settings().auth_tenant_id)
        print('管理员初始化完成')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    password = getpass.getpass('管理员密码（至少 12 位）: ')
    if password != getpass.getpass('再次输入: '):
        raise SystemExit('两次密码不同')
    asyncio.run(run(args.username, password))
