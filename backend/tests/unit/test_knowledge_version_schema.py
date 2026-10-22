from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_version import (
    KnowledgeFileUploadRequest,
    KnowledgeParsedBlock,
    KnowledgePreviewResponse,
)


def test_knowledge_file_contract_carries_upload_and_preview_metadata():
    request = KnowledgeFileUploadRequest(
        title="员工手册",
        filename="handbook.md",
        owner_id="u_admin_001",
        permission_tags=["employee"],
        effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    preview = KnowledgePreviewResponse(
        filename=request.filename,
        format="md",
        content_hash="a" * 64,
        blocks=[KnowledgeParsedBlock(text="# 员工手册", section="员工手册")],
    )
    assert request.format == "md"
    assert preview.blocks[0].section == "员工手册"


def test_knowledge_file_contract_rejects_unsafe_filename_and_hash():
    with pytest.raises(ValidationError):
        KnowledgeFileUploadRequest(title="x", filename="../secret.md")
    with pytest.raises(ValidationError):
        KnowledgePreviewResponse(filename="x.md", format="md", content_hash="bad", blocks=[])
