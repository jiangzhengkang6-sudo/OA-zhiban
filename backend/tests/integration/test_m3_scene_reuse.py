"""Formal cached reads, replay and graph boundaries for the P3 scenes."""
import pytest
from sqlalchemy import func, select

from app.core.errors import AppException
from app.models.contract_record import ContractRecord
from app.models.contract_review_version import ContractReviewVersion
from app.schemas.contract import ContractCommand
from app.schemas.report import ReportInput, ReportPlanApproval
from app.schemas.work_task import WorkTaskSourceInput, WorkTaskCommandBase, WorkTaskDecision
from app.services import contract_service, report_service, work_task_service
from tests.integration.test_m3_contract_authority import participants, create
from tests.integration.test_m3_derived_authority import ended_reimbursement, reimbursement_task, move_member
from tests.integration.test_m3_document_sources import formal_documents
from tests.integration.test_m3_formal_sources import revoke, report_plan
from tests.oa_support import oa_db


@pytest.mark.parametrize('entry', ['detail', 'versions', 'source', 'create_replay', 'command_replay'])
async def test_formal_contract_private_entries_recheck_permission(formal_documents, entry):
    async with formal_documents() as db:
        owner, reviewer = await participants(db)
        created = await create(db, owner, reviewer)
        identifier = created['contract_id']
        command = ContractCommand(action='review', idempotency_key='private-review', expected_version=created['version'])
        reviewed = await contract_service.command_contract(db, owner, identifier, command)
        assert reviewed['status'] == 'DRAFT_READY'
        await db.commit()
        await revoke(db, owner, 'contract')
        with pytest.raises(AppException) as denied:
            if entry == 'detail':
                await contract_service.get_contract(db, owner, identifier)
            elif entry == 'versions':
                await contract_service.list_versions(db, owner, identifier)
            elif entry == 'source':
                await contract_service.source_detail(db, owner, identifier, created['source_id'])
            elif entry == 'create_replay':
                await create(db, owner, reviewer)
            else:
                await contract_service.command_contract(db, owner, identifier, command)
        assert denied.value.http_status == 403


async def test_formal_contract_graph_rechecks_authority_before_persisting_node(formal_documents, monkeypatch):
    from app.graph.contract_graph import contract_graph
    async with formal_documents() as db:
        owner, reviewer = await participants(db)
        created = await create(db, owner, reviewer)
        await db.commit()

        async def stream(*args, **kwargs):
            async with formal_documents() as mutation:
                await revoke(mutation, owner, 'contract')
            yield {'extract_clauses': {'node_trace': ['extract_clauses']}}

        monkeypatch.setattr(contract_graph, 'astream', stream)
        with pytest.raises(AppException) as denied:
            await contract_service.command_contract(db, owner, created['contract_id'],
                ContractCommand(action='review', idempotency_key='revoked-node', expected_version=created['version']))
        assert denied.value.http_status == 403
        await db.rollback()
        record = await db.scalar(select(ContractRecord).where(ContractRecord.contract_id == created['contract_id']))
        assert record.status == 'PROCESSING' and record.current_version == created['version']
        assert record.node_state.get('node_trace', []) == []
        assert await db.scalar(select(func.count()).select_from(ContractReviewVersion).where(
            ContractReviewVersion.contract_id == record.id)) == 0


@pytest.mark.parametrize('entry', ['detail', 'versions', 'create_replay', 'approve_replay'])
async def test_formal_report_cached_entries_reject_changed_department(formal_documents, monkeypatch, entry):
    async with formal_documents() as db:
        actor, _, _ = await ended_reimbursement(db, monkeypatch)
        payload = ReportInput(subject='调岗前的报表', plan=report_plan('approval_outcomes'), idempotency_key='move-report')
        created = await report_service.create_report(db, actor, payload)
        command = ReportPlanApproval(idempotency_key='move-approve', expected_version=1, plan_confirmed=True)
        generated = await report_service.approve_plan(db, actor, created.report_id, command)
        assert generated.status == 'DRAFT_READY'
        await db.commit()
        await move_member(formal_documents, actor)
        with pytest.raises(AppException) as denied:
            if entry == 'detail':
                await report_service.get_report(db, actor, created.report_id)
            elif entry == 'versions':
                await report_service.list_versions(db, actor, created.report_id)
            elif entry == 'create_replay':
                await report_service.create_report(db, actor, payload)
            else:
                await report_service.approve_plan(db, actor, created.report_id, command)
        assert denied.value.http_status == 403


async def test_formal_report_discards_graph_result_after_source_revocation(formal_documents, monkeypatch):
    from app.graph.report_graph import report_graph
    async with formal_documents() as db:
        actor, _, _ = await ended_reimbursement(db, monkeypatch)
        created = await report_service.create_report(db, actor, ReportInput(subject='异步来源复核',
            plan=report_plan('approval_outcomes'), idempotency_key='async-report'))
        await db.commit()
        original = report_graph.ainvoke

        async def generate(*args, **kwargs):
            result = await original(*args, **kwargs)
            async with formal_documents() as mutation:
                await revoke(mutation, actor, 'reimbursement')
            return result

        monkeypatch.setattr(report_graph, 'ainvoke', generate)
        with pytest.raises(AppException) as denied:
            await report_service.approve_plan(db, actor, created.report_id,
                ReportPlanApproval(idempotency_key='async-approve', expected_version=1, plan_confirmed=True))
        assert denied.value.http_status == 403
        await db.rollback()


@pytest.mark.parametrize('entry', ['versions', 'create_replay', 'extract_replay', 'decide_replay'])
async def test_formal_task_batch_replays_recheck_reimbursement_source(formal_documents, monkeypatch, entry):
    async with formal_documents() as db:
        actor, identifier, _ = await ended_reimbursement(db, monkeypatch)
        batch = await reimbursement_task(db, actor, identifier)
        await revoke(db, actor, 'reimbursement')
        with pytest.raises(AppException) as denied:
            if entry == 'versions':
                await work_task_service.versions(db, actor, batch.batch_id)
            elif entry == 'create_replay':
                await work_task_service.create_batch(db, actor, WorkTaskSourceInput(source_type='approval',
                    source_id=identifier, source_version=1, idempotency_key='reimbursement-batch'))
            elif entry == 'extract_replay':
                await work_task_service.extract(db, actor, batch.batch_id, WorkTaskCommandBase(
                    idempotency_key='extract-reimbursement', expected_version=0))
            else:
                await work_task_service.decide(db, actor, batch.batch_id, WorkTaskDecision(
                    action='confirm', idempotency_key='confirm-reimbursement-task', expected_version=2,
                    selected_candidate_ids=[batch.draft.candidates[0].candidate_id], metadata_confirmed=True))
        assert denied.value.http_status == 403
        task = await work_task_service.get_task(db, actor, batch.task_ids[0])
        assert task.source is None and task.source_refs == []
        assert (await work_task_service.list_tasks(db, actor)).total == 1
