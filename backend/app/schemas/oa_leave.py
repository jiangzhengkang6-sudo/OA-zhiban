"""Typed manual leave inputs; derived days are never accepted from clients."""
from datetime import date, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OAInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


Identifier = Annotated[str, Field(min_length=1, max_length=64)]


class NormalizedLeaveFields(OAInput):
    leave_type: Annotated[str, Field(min_length=1, max_length=64)]
    start_date: date
    end_date: date
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    attachment_ids: list[Identifier] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError('结束日期不能早于开始日期')
        if len(self.attachment_ids) != len(set(self.attachment_ids)):
            raise ValueError('附件不能重复')
        return self

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def days_by_year(self) -> dict[int, int]:
        result = {}
        cursor = self.start_date
        while cursor <= self.end_date:
            boundary = min(self.end_date, date(cursor.year, 12, 31))
            result[cursor.year] = (boundary - cursor).days + 1
            if boundary == self.end_date:
                break
            cursor = boundary + timedelta(days=1)
        return result


class LeaveDraftCreate(OAInput):
    operation_id: Identifier
    workflow_definition_id: Identifier
    fields: NormalizedLeaveFields


class LeaveDraftPatch(OAInput):
    operation_id: Identifier
    expected_revision: int = Field(ge=1)
    fields: NormalizedLeaveFields


class OACommand(OAInput):
    operation_id: Identifier
    expected_revision: int = Field(ge=1)


class SubmitLeaveCommand(OACommand):
    requested_submission_version: int = Field(ge=1)


class BalanceAdjustment(OAInput):
    operation_id: Identifier
    expected_revision: int = Field(ge=0)
    user_id: Identifier
    leave_type: Identifier
    year: int = Field(ge=1900, le=9999)
    total: int = Field(ge=0, strict=True)
    reason: Annotated[str, Field(min_length=1, max_length=500)]
