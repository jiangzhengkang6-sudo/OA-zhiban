"""Separate adapter capability declaration from domain execution."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    identity: bool = False
    leave_read: bool = False
    approval_write: bool = False
    ticket_write: bool = False
    notification: bool = False


class IdentityProvider(Protocol):
    def get_user_context(self, user_id: str): ...


class LeaveProvider(Protocol):
    def get_leave_case(self, business_id: str): ...
    def get_leave_balance(self, user_id: str, leave_type: str): ...


class ApprovalProvider(Protocol):
    def get_approval_route(self, user_id: str, case): ...
    def create_or_update_approval(self, command): ...


class TicketProvider(Protocol):
    def create_or_merge_ticket(self, command): ...


class NotificationProvider(Protocol):
    def notify(self, command): ...
