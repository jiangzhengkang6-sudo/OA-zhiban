"""Task evidence and human identity validation; no database is touched."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pydantic import ValidationError

from app.schemas.work_task import WorkTaskCandidateDTO
from app.services.work_task_generator import extract_candidates, validate_candidates
from app.schemas.work_task import WorkTaskDraftDTO
from app.services import work_task_generator


def test_extraction_preserves_source_evidence_and_does_not_resolve_names():
    source = {"ref": "ticket:T-1:abc", "content": "Repair printer", "action_items": []}
    candidates = extract_candidates(source)
    assert candidates[0]["title"] == "Repair printer"
    assert candidates[0]["source_refs"] == [source["ref"]]
    assert candidates[0]["assignee_id"] is None
    assert candidates[0]["due_at"] is None


def test_candidate_rejects_naive_deadline_and_unknown_fields():
    with pytest.raises(ValidationError):
        WorkTaskCandidateDTO(candidate_id="a", title="Do work", source_refs=["s"], due_at="2026-10-20T10:00:00")
    with pytest.raises(ValidationError):
        WorkTaskCandidateDTO(candidate_id="a", title="Do work", source_refs=["s"], tool="send_mail")


def test_unknown_evidence_and_duplicate_candidate_are_rejected():
    with pytest.raises(ValueError):
        validate_candidates([{"candidate_id": "a", "title": "Do work", "source_refs": ["unknown"]}], "source")
    candidate = {"candidate_id": "a", "title": "Do work", "source_refs": ["source"]}
    with pytest.raises(ValueError):
        validate_candidates([candidate, candidate], "source")


def test_meeting_candidates_have_stable_identity():
    source = {"ref": "meeting:M-1:1", "content": "Meeting", "action_items": [{"title": "Submit report", "assignee_candidate": "Manager", "priority": "high"}]}
    first = extract_candidates(source)
    assert first == extract_candidates(source)
    assert first[0]["priority"] == "high"
    assert first[0]["assignee_id"] is None


@pytest.mark.asyncio
async def test_real_extraction_bounds_output_and_canonicalizes_model_identity(monkeypatch):
    source = {"ref": "ticket:T-1:abc", "content": "Repair printer"}
    llm = SimpleNamespace(last_usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        structured=AsyncMock(side_effect=[WorkTaskDraftDTO(candidates=[{"candidate_id": key,
            "title": "Repair printer", "assignee_id": "guessed-person", "due_at": "2026-10-20T10:00:00Z",
            "source_refs": [source["ref"]]}]) for key in ("arbitrary-first", "arbitrary-second")]))
    monkeypatch.setattr(work_task_generator, "get_settings", lambda: SimpleNamespace(llm_provider="ark"))
    monkeypatch.setattr(work_task_generator.LLMFactory, "get_llm", lambda: llm)
    usage = {}
    first = await work_task_generator.generate(source, usage)
    second = await work_task_generator.generate(source)
    assert first == second
    assert first[0]["assignee_id"] is None and first[0]["due_at"] is None
    assert usage["total_tokens"] == 20
    assert all(call.kwargs["max_tokens"] == 2048 for call in llm.structured.await_args_list)


def test_extraction_rejects_overflow_instead_of_silently_dropping_actions():
    with pytest.raises(ValueError, match="candidate limit"):
        extract_candidates({"ref": "meeting:M-1:1", "content": "Meeting",
            "action_items": [{"title": str(index)} for index in range(51)]})
