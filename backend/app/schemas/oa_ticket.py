from typing import Literal
from pydantic import Field,model_validator
from .oa_leave import OAInput,OACommand,Identifier


class FormalTicketProposal(OAInput):
    operation_id: Identifier
    thread_id: Identifier|None=None
    category: Identifier='其他'
    priority: Literal['low','medium','high']='medium'
    impact: Identifier='个人'
    summary: str=Field(min_length=1,max_length=2000)
    merge_ticket_id: Identifier|None=None
    expected_revision: int|None=Field(default=None,ge=1)

    @model_validator(mode='after')
    def merge_revision(self):
        if bool(self.merge_ticket_id)!=(self.expected_revision is not None):
            raise ValueError('合并工单必须同时提供目标和版本')
        return self


class FormalTicketCommand(FormalTicketProposal):
    confirmation_id: Identifier


class TicketHandleCommand(OACommand):
    action: Literal['claim','reassign','start','resolve']
    target_user_id: Identifier|None=None
    note: str=Field(default='',max_length=2000)

    @model_validator(mode='after')
    def valid_action(self):
        if (self.action=='reassign')!=bool(self.target_user_id):
            raise ValueError('仅改派操作需要目标人员')
        if self.action in {'resolve','reassign'} and not self.note:
            raise ValueError('请填写办理或改派说明')
        return self


class TicketFeedbackCommand(OACommand):
    resolved: bool
    comment: str=Field(min_length=1,max_length=2000)


class TicketRuleSave(OAInput):
    operation_id: Identifier
    department_id: Identifier
    code: Identifier
    category: Identifier='*'
    impact: Identifier='*'
    queue: str=Field(min_length=1,max_length=128)
    assignee_id: Identifier|None=None
    priority: int=Field(default=0,ge=0,le=1000)
    enabled: bool=True
    expected_version: int|None=Field(default=None,ge=1)
