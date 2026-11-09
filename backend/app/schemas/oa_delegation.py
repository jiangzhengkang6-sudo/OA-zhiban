from datetime import timedelta
from typing import Literal
from pydantic import AwareDatetime, Field, model_validator
from .oa_workflow import OAInput, Identifier
from .oa_leave import OACommand


class DelegationCreate(OAInput):
    operation_id: Identifier
    delegate_id: Identifier
    scene: Literal['leave', 'reimbursement']
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def window(self):
        if not self.starts_at < self.ends_at <= self.starts_at + timedelta(days=90):
            raise ValueError('委托期限须大于零且不超过 90 天')
        if not self.reason.strip():
            raise ValueError('请填写委托原因')
        return self


class DelegationRevoke(OACommand):
    pass
