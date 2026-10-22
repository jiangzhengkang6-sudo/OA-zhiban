import asyncio
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from sqlalchemy import select,func
from tests.oa_support import oa_db
from tests.api.test_oa_notification import setup,enqueue


WORKER='''
import asyncio,json,os,sys
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.core import config
from app.providers import identity
from app.db.session import AuthorizedSession
from tests.integration.test_identity_sessions import configured
config.get_settings=configured
identity.get_settings=configured
from app.services.oa_notification_worker import claim_one
async def main():
    engine=create_async_engine(os.environ['DATABASE_URL'])
    try:
        result=await claim_one(async_sessionmaker(engine,class_=AuthorizedSession,expire_on_commit=False),tenant_id=sys.argv[1])
        print(json.dumps(result))
    finally: await engine.dispose()
asyncio.run(main())
'''


async def test_two_process_claim_and_crash_recovery_never_resends_unknown(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.oa_notification import OANotificationDelivery,OANotificationAttempt
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
    def process():
        result=subprocess.run([sys.executable,'-c',WORKER,owner.tenant_id],cwd=Path(__file__).resolve().parents[2],
            env=os.environ.copy(),capture_output=True,text=True,timeout=40)
        assert result.returncode==0,result.stderr[-2500:]
        return json.loads(result.stdout.strip().splitlines()[-1])
    results=await asyncio.gather(asyncio.to_thread(process),asyncio.to_thread(process))
    claimed=[result for result in results if result]
    assert len(claimed)==1
    assert await asyncio.to_thread(process) is None
    # The winning process exited after commit, with no SMTP receipt.
    await worker.recover(oa_db,tenant_id=owner.tenant_id,now=datetime.now(timezone.utc)+timedelta(minutes=5))
    assert await asyncio.to_thread(process) is None
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery,claimed[0]['id'])).state=='UNKNOWN'
        assert await db.scalar(select(func.count()).select_from(OANotificationAttempt).where(OANotificationAttempt.tenant_id==owner.tenant_id))==1
