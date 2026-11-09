"""No arbitrary From addresses, server hosts or credentials accepted from the browser."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


def address(value):
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
        raise ValueError('请填写有效的邮箱地址，不要包含姓名或换行')
    return value


class MailDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=255)
    recipients: list[str] = Field(min_length=1, max_length=30)
    body: str = Field(min_length=1, max_length=30000)
    reply_to_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(default=0, ge=0)

    @field_validator('subject')
    @classmethod
    def header(cls, value):
        if '\r' in value or '\n' in value or '\x00' in value:
            raise ValueError('主题不能包含换行或空字符')
        return value

    @field_validator('body')
    @classmethod
    def body_valid(cls, value):
        if '\x00' in value:
            raise ValueError('正文不能包含空字符')
        return value

    @field_validator('recipients')
    @classmethod
    def recipients_valid(cls, values):
        return list(dict.fromkeys(address(v.strip()) for v in values))


class MailAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['claim', 'release', 'complete', 'reopen', 'send']
    expected_version: int = Field(ge=1)
    confirmed: bool = False


class MailMember(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str = Field(min_length=1, max_length=64)
    can_process: bool = False
    can_send: bool = False
    can_manage: bool = False


class MailMembers(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    members: list[MailMember] = Field(min_length=1, max_length=100)
