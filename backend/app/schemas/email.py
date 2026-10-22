"""Mail review contracts; attachment metadata never grants file or sending access."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmailAttachment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    sensitive: bool = False


class EmailInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    subject: str = Field(min_length=1, max_length=255)
    sender: str = Field(min_length=1, max_length=320)
    recipients: list[str] = Field(min_length=1, max_length=30)
    body: str = Field(min_length=1, max_length=30000)
    external_contact: bool = False
    attachments: list[EmailAttachment] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("recipients")
    @classmethod
    def valid_recipients(cls, values):
        result = [value.strip() for value in values]
        if any(not value or len(value) > 320 for value in result):
            raise ValueError("收件人不能为空且长度不能超过320")
        return result


class EmailSource(BaseModel):
    ref: str
    text: str
    locator: str
    content_hash: str


class EmailActionItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=2000)
    assignee_candidate: str | None = Field(default=None, max_length=255)
    due_at_candidate: str | None = Field(default=None, max_length=100)
    source_refs: list[str] = Field(min_length=1, max_length=300)
    needs_confirmation: Literal[True] = True


class EmailDraftDTO(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    category: Literal["work", "approval", "meeting", "notification", "other"]
    priority: Literal["high", "normal", "low"]
    summary: str = Field(min_length=1, max_length=4000)
    action_items: list[EmailActionItem] = Field(default_factory=list, max_length=100)
    reply_subject: str = Field(min_length=1, max_length=300)
    reply_body: str = Field(min_length=1, max_length=20000)
    source_refs: list[str] = Field(min_length=1, max_length=300)


class EmailCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)


class EmailDraftUpdate(EmailCommand):
    expected_version: int = Field(ge=1)
    draft: EmailDraftDTO


class EmailDecision(EmailCommand):
    expected_version: int = Field(ge=1)
    action: Literal["confirm", "reject", "regenerate"]
    reason: str | None = Field(default=None, max_length=2000)
    metadata_confirmed: bool = False
    warnings_acknowledged: bool = False
    secondary_confirmed: bool = False


class EmailSummary(BaseModel):
    email_id: str
    thread_id: str
    subject: str
    status: str
    version: int | None
    available_actions: list[str]
    created_at: datetime
    updated_at: datetime


class EmailResponse(EmailSummary):
    sender: str
    recipients: list[str]
    body: str
    external_contact: bool
    attachments: list[EmailAttachment]
    sources: list[EmailSource]
    draft: EmailDraftDTO | None
    checks: list[dict]
    secondary_confirmation_required: bool
    confirmation: dict | None = None
    error: dict | None = None
    external_writes: Literal[False] = False


class EmailVersion(BaseModel):
    version: int
    draft: EmailDraftDTO
    checks: list[dict]
    edited_by: str | None
    created_at: datetime


class EmailPage(BaseModel):
    items: list[EmailSummary]
    total: int
    page: int
    page_size: int
