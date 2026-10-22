"""Synthetic deterministic report acceptance; not a real-model benchmark."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.context import CurrentUser
from app.core.errors import AppException
from app.schemas.report import ReportPlan
from app.services.report_generator import generate, validate_draft
from app.services.report_query import scope_fingerprint


FIXTURE = json.loads(Path(__file__).with_name("p3_report_cases.json").read_text(encoding="utf-8"))
EVIDENCE = {"metrics": [
    {"metric_id": "ticket_volume", "current": 1, "previous": 2, "change_percent": -50},
    {"metric_id": "approval_outcomes", "current": 8, "previous": 3, "change_percent": 166.67},
]}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
async def test_report_synthetic_rules(case):
    if case["kind"] == "draft":
        with pytest.raises(ValueError):
            validate_draft({"summary": case["summary"], "metric_refs": case["refs"], "possible_causes": []}, EVIDENCE)
    elif case["kind"] == "plan":
        if not case["allowed"]:
            with pytest.raises(ValidationError):
                ReportPlan(metrics=["ticket_volume"], start=case["start"], end=case["end"])
        else:
            plan = ReportPlan(metrics=["ticket_volume"], start=case["start"], end=case["end"])
            assert plan.start.isoformat() == case["utc_start"]
            assert plan.previous_start.isoformat() == case["previous_start"]
            assert plan.previous_end == plan.start
            assert plan.previous_end - plan.previous_start == plan.end - plan.start
    elif case["kind"] == "scope":
        actor = CurrentUser(user_id="synthetic", tenant_id="synthetic-tenant", roles=case["roles"], data_scope=case["data_scope"])
        if case["allowed"]:
            assert scope_fingerprint(actor, case["scope"])
        else:
            with pytest.raises(AppException) as failure:
                scope_fingerprint(actor, case["scope"])
            assert failure.value.http_status == 403
    elif case["kind"] == "snapshot":
        snapshot = {"metrics": [{"metric_id": "ticket_volume", "name": "工单量", "unit": "条",
            "current": case["current"], "previous": case["previous"], "change_percent": case["change_percent"]}]}
        original = deepcopy(snapshot)
        draft = await generate(snapshot)
        assert snapshot == original
        assert draft.metric_refs == ["ticket_volume"]
        assert not any(char.isnumeric() for char in draft.summary)
    else:
        pytest.fail("unknown synthetic report case kind")


def test_report_splits_are_independent_and_have_equal_coverage():
    development = {case["id"] for case in FIXTURE["cases"] if case["split"] == "development"}
    acceptance = {case["id"] for case in FIXTURE["cases"] if case["split"] == "acceptance"}
    assert len(development) == len(acceptance) == 6
    assert development.isdisjoint(acceptance)


def test_report_scope_fingerprint_changes_after_tenant_or_scope_revocation():
    actor = CurrentUser(user_id="synthetic", tenant_id="tenant-a", roles=["admin"], data_scope={"all": True})
    original = scope_fingerprint(actor, "own")
    actor.tenant_id = "tenant-b"
    assert scope_fingerprint(actor, "own") != original
    actor.tenant_id = "tenant-a"
    actor.data_scope = {"all": False}
    assert scope_fingerprint(actor, "own") != original
