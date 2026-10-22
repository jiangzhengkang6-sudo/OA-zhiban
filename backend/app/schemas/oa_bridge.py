"""Typed agent bridge inputs; actor and confirmation come from trusted context."""
from typing import Annotated, Literal
from pydantic import Field

from .oa_leave import Identifier, OAInput, LeaveDraftPatch, SubmitLeaveCommand
from .oa_workflow import DecideNodeCommand


class BridgeLeaveSubmit(SubmitLeaveCommand):
    action: Literal['submit'] = 'submit'
    business_id: Identifier
    thread_id: Identifier | None = None
    review_route_hash: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')] | None = None


class BridgeApprovalDecision(DecideNodeCommand):
    node_id: Identifier
    thread_id: Identifier | None = None


class BridgeLeaveEdit(LeaveDraftPatch):
    business_id: Identifier
    thread_id: Identifier | None = None


class BridgeNotification(OAInput):
    user_id: Identifier
    channel: Literal['oa_inbox', 'inbox'] = 'oa_inbox'
    title: Annotated[str, Field(min_length=1, max_length=120)]
    body: Annotated[str, Field(min_length=1, max_length=2000)]
    business_id: Annotated[str, Field(max_length=64)] = ''
    idempotency_key: Identifier
