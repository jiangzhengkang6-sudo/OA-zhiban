"""Synthetic split fixture verification, not a real-model quality benchmark."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.services import work_task_generator


FIXTURE = json.loads(Path(__file__).with_name("p3_work_task_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
@pytest.mark.asyncio
async def test_synthetic_extraction_preserves_evidence_and_human_metadata(case, monkeypatch):
    source = dict(case["source"])
    if "content_size" in case:
        source["content"] = "X" * case["content_size"]
    if "action_count" in case:
        source["action_items"] = source["action_items"] * case["action_count"]
    monkeypatch.setattr(work_task_generator, "get_settings", lambda: SimpleNamespace(llm_provider="mock"))
    async def run():
        if case.get("operation") == "validate":
            return work_task_generator.validate_candidates(case["candidates"], source["ref"])
        if case.get("operation") == "generate":
            return await work_task_generator.generate(source)
        return work_task_generator.extract_candidates(source)
    if "expected_error" in case:
        with pytest.raises(ValueError, match=case["expected_error"]):
            await run()
        return
    candidates = await run()
    assert [candidate["title"] for candidate in candidates] == case["titles"]
    assert all(candidate["source_refs"] == [case["source"]["ref"]] for candidate in candidates)
    assert all(candidate["assignee_id"] is None and candidate["due_at"] is None for candidate in candidates)
    assert candidates == await run()


def test_development_and_acceptance_ids_are_disjoint():
    development = {case["id"] for case in FIXTURE["cases"] if case["split"] == "development"}
    acceptance = {case["id"] for case in FIXTURE["cases"] if case["split"] == "acceptance"}
    assert len(development) == len(acceptance) == 6
    assert development.isdisjoint(acceptance)
