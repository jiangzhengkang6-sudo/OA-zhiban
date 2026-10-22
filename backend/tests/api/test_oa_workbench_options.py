import pytest
from app.core.errors import AppException
from app.schemas.oa_workflow import WorkflowSave,PublishWorkflow
from tests.oa_support import oa_db,seed
from tests.unit.test_oa_workflow_definition import definition


async def test_directory_is_minimal_department_scoped_and_permission_checked(oa_db):
    from app.services import oa_workflow_service as service
    async with oa_db() as db:
        actor=await seed(db,resources=['workflow'])
        colleague=await seed(db,tenant=actor.tenant_id,department=actor.depts[0])
        other=await seed(db,tenant=actor.tenant_id,resources=['workflow'])
        await db.commit()
        options=await service.workbench_options(db,actor)
        assert {u['id'] for u in options['users']}=={actor.user_id,colleague.user_id}
        assert all(set(u)=={'id','name'} for u in options['users'])
        assert other.user_id not in str(options)
        with pytest.raises(AppException): await service.workbench_options(db,colleague)


async def test_available_workflow_exposes_published_form_only(oa_db):
    from app.services import oa_workflow_service as service
    async with oa_db() as db:
        admin=await seed(db,resources=['workflow'])
        employee=await seed(db,tenant=admin.tenant_id,department=admin.depts[0],resources=['leave'])
        saved=await service.save_definition(db,admin,WorkflowSave(operation_id='save',department_id=admin.depts[0],code='ui',name='请假',definition=definition()))
        await service.publish_definition(db,admin,saved['id'],PublishWorkflow(operation_id='publish',expected_revision=1))
        changed=definition();changed['form']['leave_types']=['other']
        await service.save_definition(db,admin,WorkflowSave(operation_id='edit',expected_revision=2,department_id=admin.depts[0],code='ui',name='请假',definition=changed),saved['id'])
        result=await service.list_definitions(db,employee,available=True)
        assert result[0]['form']['leave_types']==['annual','sick']
        assert set(result[0])=={'id','name','published_version','form'}
