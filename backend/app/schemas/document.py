"""Platform-local document input, revision and human decision contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    template_id: Literal["official", "notice", "report", "summary"]
    subject: str = Field(min_length=1, max_length=255)
    recipient: str = Field(min_length=1, max_length=500)
    deadline: str = Field(default="", max_length=100)
    basis: str = Field(default="", max_length=10000)
    key_points: str = Field(min_length=1, max_length=20000)
    classification: Literal["public", "internal", "confidential"] = "internal"
    distribution: str = Field(min_length=1, max_length=500)
    use_knowledge: bool = False
    idempotency_key: str = Field(min_length=1, max_length=128)


class DocumentTemplate(BaseModel):
    id: str
    kind: str
    name: str
    version: int
    sections: list[str]


class DocumentCheck(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str


class DocumentSource(BaseModel):
    ref: str
    kind: Literal["input", "knowledge"]
    title: str
    content: str
    content_hash: str
    source_location: str
    source_id: str | None = None
    version_id: str | None = None
    version: int | None = None


class DocumentDraftDTO(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    body: str = Field(min_length=1, max_length=40000)
    source_refs: list[str] = Field(min_length=1, max_length=20)


class DocumentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)


class DocumentDraftUpdate(DocumentCommand):
    expected_version: int = Field(ge=1)
    draft: DocumentDraftDTO


class DocumentDecision(DocumentCommand):
    expected_version: int = Field(ge=1)
    action: Literal["confirm", "reject", "regenerate"]
    reason: str | None = Field(default=None, max_length=2000)
    metadata_confirmed: bool = False
    warnings_acknowledged: bool = False


class DocumentVersion(BaseModel):
    version: int
    draft: DocumentDraftDTO
    checks: list[DocumentCheck]
    edited_by: str | None
    created_at: datetime


class DocumentSummary(BaseModel):
    document_id: str
    thread_id: str
    subject: str
    status: str
    version: int | None
    available_actions: list[str]
    created_at: datetime
    updated_at: datetime


class DocumentResponse(DocumentSummary):
    template: DocumentTemplate
    recipient: str
    deadline: str
    classification: str
    distribution: str
    sources: list[DocumentSource]
    draft: DocumentDraftDTO | None
    checks: list[DocumentCheck]
    confirmation: dict | None = None
    error: dict | None = None
    external_writes: Literal[False] = False


class DocumentPage(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int
    page_size: int
