from copy import deepcopy

import pytest
from sqlalchemy import select
from app.core.errors import AppException
from app.models.identity import OAUser
from app.models.oa_workflow import OAWorkflowVersion
from app.schemas.oa_workflow import WorkflowSave, PublishWorkflow
from app.schemas.oa_leave import NormalizedLeaveFields
from tests.oa_support import oa_db, seed
from tests.unit.test_oa_workflow_definition import definition


async def test_publish_versions_and_route_snapshot(oa_db):
    from app.services import oa_workflow_service as service
    async with oa_db() as db:
        manager = await seed(db, resources=['approval','workflow'])
        applicant = await seed(db, tenant=manager.tenant_id, department=manager.depts[0],
                               resources=['leave'], manager=manager.user_id)
        await db.commit()
        payload = WorkflowSave(operation_id='save',department_id=manager.depts[0],code='leave',name='请假流程',definition=definition())
        saved = await service.save_definition(db, manager, payload)
        replay = await service.save_definition(db, manager, payload)
        assert replay == saved
        with pytest.raises(AppException): await service.current_version(db, applicant, saved['id'])
        published = await service.publish_definition(db, manager, saved['id'], PublishWorkflow(expected_revision=1,operation_id='publish'))
        await db.commit()
        old = await db.get(OAWorkflowVersion, published.result['id'])
        fields = NormalizedLeaveFields(leave_type='annual',start_date='2026-10-18',end_date='2026-10-19',reason='测试')
        route = await service.resolve_route(db, applicant, old, fields)
        assert route.nodes[0]['seats'][0]['user_id'] == manager.user_id
        frozen = deepcopy(route.nodes)
        payload.definition.rules.timeout_hours = 72
        payload.operation_id = 'save2'
        payload.expected_revision = 2
        await service.save_definition(db, manager, payload, saved['id'])
        newer = await service.publish_definition(db, manager, saved['id'], PublishWorkflow(expected_revision=3,operation_id='publish2'))
        await db.commit()
        new = await db.get(OAWorkflowVersion, newer.result['id'])
        assert (old.version,new.version,old.form_version,new.form_version,old.rule_version,new.rule_version)==(1,2,1,1,1,2)
        assert old.package['rules']['timeout_hours'] == 48
        (await db.get(OAUser, manager.user_id)).status = 'disabled'
        await db.flush()
        paused = await service.resolve_route(db, applicant, old, fields)
        assert paused.pause_reasons and route.nodes == frozen


async def test_duplicate_candidates_and_self_pause(oa_db):
    from app.services import oa_workflow_service as service
    async with oa_db() as db:
        actor = await seed(db, resources=['workflow','approval','leave'])
        await db.commit()
        value = definition()
        value['nodes'][0]['mode'] = 'all'
        value['nodes'][0]['selector'] = dict(kind='users',user_ids=[actor.user_id,actor.user_id])
        saved = await service.save_definition(db,actor,WorkflowSave(operation_id='save',department_id=actor.depts[0],code='self',name='自审检查',definition=value))
        pub = await service.publish_definition(db,actor,saved['id'],PublishWorkflow(expected_revision=1,operation_id='publish'))
        version = await db.get(OAWorkflowVersion,pub.result['id'])
        route = await service.resolve_route(db,actor,version,NormalizedLeaveFields(leave_type='annual',start_date='2026-10-18',end_date='2026-10-18',reason='test'))
        assert route.pause_reasons
        assert len(route.nodes[0]['seats']) == 1


async def test_branch_role_and_missing_manager(oa_db):
    from app.services import oa_workflow_service as service
    from app.models.identity import OAUserRole
    async with oa_db() as db:
        reviewer = await seed(db, resources=['workflow', 'approval'])
        applicant = await seed(db, tenant=reviewer.tenant_id, department=reviewer.depts[0], resources=['leave'])
        role_id = await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id == reviewer.user_id))
        await db.commit()
        value = definition()
        value['entry_id'] = 'branch'
        value['nodes'].insert(0, dict(id='branch',kind='branch',cases=[dict(field='days',op='gt',value=1,next_id='role')],default_next_id='review'))
        value['nodes'].insert(1, dict(id='role',kind='approval',mode='all',selector=dict(kind='role',role_id=role_id),next_id='end'))
        saved = await service.save_definition(db, reviewer, WorkflowSave(operation_id='save',department_id=reviewer.depts[0],code='branches',name='分支',definition=value))
        published = await service.publish_definition(db,reviewer,saved['id'],PublishWorkflow(operation_id='publish',expected_revision=1))
        version = await db.get(OAWorkflowVersion,published.result['id'])
        one = NormalizedLeaveFields(leave_type='annual',start_date='2026-10-18',end_date='2026-10-18',reason='test')
        short = await service.resolve_route(db,applicant,version,one)
        assert short.pause_reasons and short.nodes[0]['key'] == 'review'
        one.end_date = __import__('datetime').date(2026,10,19)
        longer = await service.resolve_route(db,applicant,version,one)
        assert not longer.pause_reasons
        assert longer.nodes[0]['key'] == 'role'
        assert [seat['user_id'] for seat in longer.nodes[0]['seats']] == [reviewer.user_id]
