"""Contracts shared by file upload, parsing preview and version services."""

from datetime import datetime
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

KnowledgeFormat = Literal["md", "markdown", "html", "htm", "pdf"]


class KnowledgeFileUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    format: KnowledgeFormat = "md"
    permission_tags: list[str] = Field(default_factory=list, max_length=32)
    owner_id: str = Field(default="u_admin_001", min_length=1, max_length=64)
    effective_at: datetime | None = None
    expire_at: datetime | None = None

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if PurePath(normalized).name != normalized or normalized in {".", ".."}:
            raise ValueError("filename must not contain a path")
        return normalized


class KnowledgeParsedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    paragraph: int | None = Field(default=None, ge=1)


class KnowledgePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    format: KnowledgeFormat
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    blocks: list[KnowledgeParsedBlock]


class KnowledgeVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    format: KnowledgeFormat = "md"
    permission_tags: list[str] = Field(default_factory=list, max_length=32)
    owner_id: str = Field(default="u_admin_001", min_length=1, max_length=64)
    effective_at: datetime | None = None
    expire_at: datetime | None = None


class KnowledgeVersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    version: int
    status: str
    parse_status: str
    content_hash: str | None = None
    permission_tags: list[str]
    effective_at: datetime | None = None
    expire_at: datetime | None = None

