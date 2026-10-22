import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.models.identity import OAMembership
from app.models.oa_workflow import OAWorkflowNode,OAWorkflowSeat,OAWorkflowEvent
from tests.oa_support import oa_db
from tests.api.test_oa_approval_modes import submitted


WORKER='''
import asyncio,json,os,sys
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.core import config
from app.providers import identity
from app.db.session import AuthorizedSession
from app.models.identity import OAUser
from app.services.identity_service import current_identity
from tests.integration.test_identity_sessions import configured
config.get_settings=configured
identity.get_settings=configured
from app.services.oa_workflow_scheduler import scan
async def main():
    engine=create_async_engine(os.environ['DATABASE_URL'])
    try:
        async with async_sessionmaker(engine,class_=AuthorizedSession,expire_on_commit=False)() as db:
            actor=await current_identity(db,await db.get(OAUser,sys.argv[1]))
            result=await scan(db,actor=actor)
            await db.commit()
            print(json.dumps(result))
    finally:
        await engine.dispose()
asyncio.run(main())
'''


async def test_independent_processes_and_restart_do_not_repeat_escalation(oa_db):
    async with oa_db() as db:
        first,_,replacement,actor,_=await submitted(db)
        member=await db.get(OAMembership,(actor.tenant_id,first.user_id))
        member.manager_id=replacement.user_id
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id))
        node.due_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        node_id=node.id
        await db.commit()
    def process():
        result=subprocess.run([sys.executable,'-c',WORKER,first.user_id],cwd=Path(__file__).resolve().parents[2],
            env=os.environ.copy(),capture_output=True,text=True,timeout=40)
        assert result.returncode==0,result.stderr[-3000:]
        return json.loads(result.stdout.strip().splitlines()[-1])
    results=await asyncio.gather(asyncio.to_thread(process),asyncio.to_thread(process))
    assert all(not result['errors'] for result in results)
    assert sum(result['processed'] for result in results)==1
    assert (await asyncio.to_thread(process))['processed']==0
    async with oa_db() as db:
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node_id))
        assert seat.escalated and seat.effective_user_id==replacement.user_id
        assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(
            OAWorkflowEvent.tenant_id==actor.tenant_id,OAWorkflowEvent.action=='workflow.escalate'))==1
