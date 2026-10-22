"""Exact CNY input; whitespace, exponent notation and rounding are rejected."""
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator
from .oa_leave import OAInput, Identifier, OACommand

MAX_AMOUNT_MINOR = 99999999999


def money_minor(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,2})?',value):
        raise ValueError('金额须为普通十进制字符串，最多两位小数')
    cents=int(Decimal(value)*100)
    if not 1 <= cents <= MAX_AMOUNT_MINOR:
        raise ValueError('金额须大于零且不超过 999999999.99 元')
    return cents


def format_money(cents):
    return f'{cents//100}.{cents%100:02d}'


class ReimbursementFields(OAInput):
    purpose: str = Field(min_length=1,max_length=2000)
    expense_date: date
    category: Identifier
    amount: str
    currency: Literal['CNY'] = 'CNY'
    attachment_ids: list[Identifier] = Field(default_factory=list,max_length=20)

    @field_validator('amount',mode='before')
    @classmethod
    def exact_amount(cls,value):
        return format_money(money_minor(value))

    @model_validator(mode='after')
    def unique_attachments(self):
        if len(self.attachment_ids)!=len(set(self.attachment_ids)):
            raise ValueError('发票附件不能重复')
        return self

    @property
    def amount_minor(self):
        return money_minor(self.amount)


class ReimbursementDraftCreate(OAInput):
    operation_id: Identifier
    workflow_definition_id: Identifier
    fields: ReimbursementFields


class ReimbursementDraftPatch(OACommand):
    fields: ReimbursementFields


class SubmitReimbursementCommand(OACommand):
    requested_submission_version: int = Field(ge=1)
