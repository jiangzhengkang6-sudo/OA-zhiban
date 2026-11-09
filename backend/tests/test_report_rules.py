from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def test_report_plan_normalizes_shanghai_midnight_and_equal_previous_interval():
    from app.schemas.report import ReportPlan
    plan = ReportPlan(metrics=["ticket_volume"], start="2026-10-01", end="2026-10-08")
    assert plan.start == datetime(2026, 9, 30, 16, tzinfo=timezone.utc)
    assert plan.previous_start == datetime(2026, 9, 23, 16, tzinfo=timezone.utc)
    assert plan.previous_end == plan.start


@pytest.mark.parametrize("extra", [{"sql": "DELETE FROM ticket_record"}, {"tenant_id": "other"}, {"metrics": ["secret_table"]}])
def test_plan_rejects_unregistered_queries(extra):
    from app.schemas.report import ReportPlan
    with pytest.raises(ValidationError):
        ReportPlan(**dict({"metrics": ["ticket_volume"], "start": "2026-10-01", "end": "2026-10-08"}, **extra))


def test_summary_rejects_fabricated_number_and_reference():
    from app.services.report_generator import validate_draft
    snapshot = {"metrics": [{"metric_id": "ticket_volume", "current": 2, "previous": 0}]}
    assert validate_draft({"summary": "工单量需结合统计表核查。", "metric_refs": ["ticket_volume"], "possible_causes": []}, snapshot)
    for summary, refs in [("共计 999 条", ["ticket_volume"]), ("工单999条", ["ticket_volume"]), ("共计 2 条", ["secret"]), ("完成率 100%", ["ticket_volume"])]:
        with pytest.raises(ValueError):
            validate_draft({"summary": summary, "metric_refs": refs, "possible_causes": []}, snapshot)


@pytest.mark.parametrize("summary", ["本期2条，前期1条", "审批本期8条", "本期２条", "工单量二条", "本期100%"])
def test_summary_rejects_swapped_periods_cross_metric_and_unicode_numbers(summary):
    from app.services.report_generator import validate_draft
    snapshot = {"metrics": [
        {"metric_id": "ticket_volume", "current": 1, "previous": 2, "change_percent": -50},
        {"metric_id": "approval_outcomes", "current": 8, "previous": 3, "change_percent": 166.7},
    ]}
    with pytest.raises(ValueError):
        validate_draft({"summary": summary, "metric_refs": ["ticket_volume", "approval_outcomes"], "possible_causes": []}, snapshot)


@pytest.mark.parametrize("word", ["一致", "统一", "进一步"])
def test_report_prose_allows_fixed_nonquantity_words_without_unblocking_adjacent_numbers(word):
    from app.services.report_generator import validate_draft
    snapshot = {"metrics": [{"metric_id": "ticket_volume", "current": 1, "previous": 2}]}
    draft = {"summary": f"数据口径需{word}核查。", "metric_refs": ["ticket_volume"],
        "possible_causes": [f"可能需要{word}核对，仍待证据确认。"]}
    assert validate_draft(draft, snapshot)
    for quantity in ("二十条", "百分之百", "２０条", "2条", "①条"):
        with pytest.raises(ValueError):
            validate_draft({**draft, "summary": word + quantity}, snapshot)
        with pytest.raises(ValueError):
            validate_draft({**draft, "possible_causes": [word + quantity]}, snapshot)


@pytest.mark.parametrize("nonempty", ["report_record", "report_version", None])
def test_report_migration_checks_both_tables_before_any_downgrade_mutation(monkeypatch, nonempty):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import Mock
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0020_report_agent.py"
    spec = importlib.util.spec_from_file_location("report_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    executed = []

    def execute(statement):
        table = str(statement).split()[-1]
        executed.append(table)
        return SimpleNamespace(scalar_one=lambda: int(table == nonempty))

    operations = SimpleNamespace(get_bind=lambda: SimpleNamespace(execute=execute), drop_table=Mock(), drop_index=Mock())
    monkeypatch.setattr(migration, "op", operations)
    if nonempty:
        with pytest.raises(RuntimeError, match="contains business data"):
            migration.downgrade()
        operations.drop_table.assert_not_called()
        operations.drop_index.assert_not_called()
    else:
        migration.downgrade()
        assert executed == ["report_version", "report_record"]
        assert [call.args[0] for call in operations.drop_table.call_args_list] == ["report_version", "report_record"]


def test_report_plan_enforces_query_budget_and_nonempty_range():
    from app.schemas.report import ReportPlan
    for start, end in [("2026-10-01", "2026-10-01"), ("2025-01-01", "2026-10-01")]:
        with pytest.raises(ValidationError):
            ReportPlan(metrics=["ticket_volume"], start=start, end=end)


@pytest.mark.asyncio
async def test_real_report_generator_bounds_output_and_preserves_usage_without_network(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services import report_generator
    from app.schemas.report import ReportDraftDTO
    snapshot = {"metrics": [{"metric_id": "ticket_volume", "current": 2, "previous": 1,
        "source_ids": ["private-id"], "buckets": [{"day": "2026-10-01", "value": 2}]}]}
    client = SimpleNamespace(structured=AsyncMock(return_value=ReportDraftDTO(summary="工单数据待核查。",
        metric_refs=["ticket_volume"], possible_causes=[])), last_usage={"prompt_tokens": 21, "completion_tokens": 12, "total_tokens": 33})
    monkeypatch.setattr(report_generator, "get_settings", lambda: SimpleNamespace(llm_provider="ark"))
    monkeypatch.setattr(report_generator.LLMFactory, "get_llm", lambda: client)
    usage = {}
    draft = await report_generator.generate(snapshot, usage=usage)
    assert draft.summary == "工单数据待核查。"
    assert client.structured.call_args.kwargs["max_tokens"] == 2048
    assert "private-id" not in str(client.structured.call_args)
    assert "buckets" not in str(client.structured.call_args)
    import json
    evidence = json.loads(client.structured.call_args.args[0][-1]['content'])
    assert evidence == {'metrics': [{'metric_id': 'ticket_volume', 'name': 'ticket_volume',
        'comparison_status': 'comparable', 'direction': '上升'}]}
    assert usage == client.last_usage
    client.structured.return_value = ReportDraftDTO(summary="本期2条。", metric_refs=["ticket_volume"], possible_causes=[])
    failed_usage = {}
    with pytest.raises(ValueError):
        await report_generator.generate(snapshot, usage=failed_usage)
    assert failed_usage == client.last_usage


@pytest.mark.asyncio
async def test_report_query_enforces_per_metric_source_row_budget_without_fabrication(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.core.context import CurrentUser
    from app.schemas.report import ReportPlan
    from app.services import report_query
    result = SimpleNamespace(all=lambda: [object()] * (report_query.MAX_SOURCE_ROWS + 1))
    execute = AsyncMock(return_value=result)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def begin(self):
            return self

    session = Session()
    session.execute = execute
    session.rollback = AsyncMock()
    monkeypatch.setattr(report_query, "async_session_factory", lambda: session)
    monkeypatch.setattr(report_query, 'require_fresh_identity', AsyncMock(side_effect=lambda actor, **kwargs: actor))
    with pytest.raises(ValueError, match="source row budget exceeded"):
        await report_query.execute_plan(CurrentUser(user_id="synthetic", tenant_id="synthetic", roles=["employee"]),
            ReportPlan(metrics=["ticket_volume"], start="2026-10-01", end="2026-10-08"))
    statement = execute.call_args.args[0]
    assert statement._limit_clause.value == 10001
    session.rollback.assert_awaited_once()
