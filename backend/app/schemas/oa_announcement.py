from pydantic import Field
from .oa_leave import OAInput, Identifier, OACommand


class AnnouncementCreate(OAInput):
    operation_id: Identifier
    department_id: Identifier
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class AnnouncementUpdate(OACommand):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
