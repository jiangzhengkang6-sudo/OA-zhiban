from pydantic import Field
from .oa_leave import OAInput,Identifier


class ContactSave(OAInput):
    operation_id: Identifier
    email: str=Field(max_length=254)
    enabled: bool
    wecom_enabled: bool | None=None


class NotificationRetry(OAInput):
    operation_id: Identifier
    note: str=Field(min_length=1,max_length=1000)
