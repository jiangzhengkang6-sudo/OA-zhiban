"""Configurable HTTP adapter for a real OA authority."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import AppException, dependency_failed
from ..providers.base import ProviderCapabilities
from .oa_adapter import (
    ApprovalCommand, ApprovalRoute, Balance, LeaveCase, LeaveEditCommand,
    NotificationCommand, NotificationResult, OAResult, TicketCommand,
    TicketResult, UserContext,
)


class RealOAAdapter:
    """HTTP implementation of the OA adapter contract."""

    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self._base_url = self.settings.oa_base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=self.settings.oa_timeout_seconds, transport=transport)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.settings.oa_api_key:
            headers["Authorization"] = f"Bearer {self.settings.oa_api_key}"
        return headers

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            return body["data"]
        if not isinstance(body, dict):
            raise ValueError("OA 响应不是 JSON 对象")
        return body

    def _request(self, method: str, path: str, *, read_only: bool, idempotency_key: str = "", json: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._base_url:
            raise dependency_failed("真实 OA 未配置地址")
        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        attempts = self.settings.oa_read_retries + 1 if read_only else 1
        for attempt in range(attempts):
            response = None
            try:
                response = self._client.request(method, path, headers=headers, json=json)
                retryable = response.status_code in {408, 429} or response.status_code >= 500
                if retryable and read_only and attempt + 1 < attempts:
                    continue
                response.raise_for_status()
                return self._payload(response)
            except (httpx.HTTPError, ValueError) as exc:
                if (
                    read_only
                    and attempt + 1 < attempts
                    and isinstance(exc, httpx.RequestError)
                ):
                    continue
                raise dependency_failed("真实 OA 请求失败", {"status_code": getattr(response, "status_code", None), "operation": path}) from exc
        raise dependency_failed("真实 OA 请求失败", {"operation": path})

    def _read(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, read_only=True)

    def _write(self, path: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        return self._request("POST", path, read_only=False, idempotency_key=key, json=payload)

    def probe_capabilities(self) -> ProviderCapabilities:
        if not self._base_url:
            return ProviderCapabilities()
        try:
            raw = self._read("/capabilities")
            values = raw.get("capabilities", raw)
            fields = ProviderCapabilities.__dataclass_fields__
            return ProviderCapabilities(**{field: bool(values.get(field, False)) for field in fields})
        except Exception:
            return ProviderCapabilities()

    def get_user_context(self, user_id: str) -> UserContext:
        return UserContext.model_validate(self._read(f"/users/{quote(user_id, safe='')}"))

    def get_leave_case(self, business_id: str) -> LeaveCase:
        return LeaveCase.model_validate(self._read(f"/leaves/{quote(business_id, safe='')}"))

    def get_leave_balance(self, user_id: str, leave_type: str) -> Balance:
        return Balance.model_validate(self._read(f"/users/{quote(user_id, safe='')}/leave-balance/{quote(leave_type, safe='')}"))

    def get_approval_route(self, user_id: str, case: LeaveCase) -> ApprovalRoute:
        return ApprovalRoute.model_validate(self._read(f"/leaves/{quote(case.business_id, safe='')}/approval-route?user_id={quote(user_id, safe='')}"))

    def create_or_update_approval(self, command: ApprovalCommand) -> OAResult:
        return OAResult.model_validate(self._write("/approvals", command.model_dump(mode="json"), command.idempotency_key))

    def get_approval_result(self, idempotency_key: str) -> OAResult | None:
        try:
            return OAResult.model_validate(self._read(f"/approvals/results/{quote(idempotency_key, safe='')}"))
        except AppException as exc:
            if isinstance(exc.detail, dict) and exc.detail.get("status_code") == 404:
                return None
            raise

    def edit_leave_case(self, command: LeaveEditCommand) -> OAResult:
        business_id = quote(command.business_id, safe="")
        return OAResult.model_validate(self._write(f"/leaves/{business_id}/edit", command.model_dump(mode="json"), command.idempotency_key))

    def get_leave_edit_result(self, idempotency_key: str) -> OAResult | None:
        try:
            return OAResult.model_validate(self._read(f"/leaves/edits/{quote(idempotency_key, safe='')}"))
        except AppException as exc:
            if isinstance(exc.detail, dict) and exc.detail.get("status_code") == 404:
                return None
            raise

    def get_notification_result(self, idempotency_key: str) -> NotificationResult | None:
        try:
            return NotificationResult.model_validate(self._read(f"/notifications/{quote(idempotency_key, safe='')}"))
        except AppException as exc:
            if isinstance(exc.detail, dict) and exc.detail.get("status_code") == 404:
                return None
            raise

    def create_or_merge_ticket(self, command: TicketCommand) -> TicketResult:
        return TicketResult.model_validate(self._write("/tickets", command.model_dump(mode="json"), command.idempotency_key))

    def notify(self, command: NotificationCommand) -> NotificationResult:
        key = command.idempotency_key or f"notify:{command.user_id}:{command.business_id}"
        return NotificationResult.model_validate(self._write("/notifications", command.model_dump(mode="json"), key))
