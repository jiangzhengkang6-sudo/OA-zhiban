"""
OA 智能体管理系统 - Mock OA 适配器实现。

以内存静态数据模拟现有 OA 权威系统，读操作直接返回，写操作按 idempotency_key 幂等去重
并记录到状态（可选落盘 mock_state.json）。提供故障注入开关用于异常验收（依赖超时、无
代理人）。仅用于开发与测试，生产不加载。
"""

import json
import os
import tempfile
from typing import Any, Optional

from ..core.config import get_settings
from .mock_data import get_initial_state
from .oa_adapter import (
    ApprovalCommand,
    ApprovalRoute,
    ApprovalNode,
    Balance,
    LeaveCase,
    LeaveEditCommand,
    NotificationCommand,
    NotificationResult,
    OAResult,
    TicketCommand,
    TicketResult,
    UserContext,
)


class MockAdapter:
    """Mock OA 适配器实现。"""

    def __init__(self) -> None:
        """初始化：加载初始状态或已持久化状态。"""
        self._settings = get_settings()
        self._state = self._load_state()
        self._idempotency: dict[str, Any] = {}
        # 故障注入开关（用于异常验收）
        self.simulate_timeout = False
        self.simulate_route_missing = False

    # ------------------------------------------------------------------ #
    # 只读接口
    # ------------------------------------------------------------------ #
    def get_user_context(self, user_id: str) -> Optional[UserContext]:
        """读取用户上下文。

        Args:
            user_id: 用户 ID。

        Returns:
            Optional[UserContext]: 用户上下文，不存在时 None。
        """
        raw = self._state["users"].get(user_id)
        if not raw:
            return None
        return UserContext(
            user_id=raw["user_id"],
            tenant_id=raw["tenant_id"],
            name=raw["name"],
            dept_id=raw["dept_id"],
            dept_name=raw["dept_name"],
            roles=list(raw.get("roles", [])),
            data_scope=raw.get("data_scope", {}),
        )

    def get_leave_case(self, business_id: str) -> Optional[LeaveCase]:
        """读取请假单快照。

        Args:
            business_id: 业务单据号。

        Returns:
            Optional[LeaveCase]: 请假单，不存在时 None。
        """
        raw = self._state["leave_cases"].get(business_id)
        if not raw:
            return None
        return LeaveCase(**raw)

    def get_leave_balance(self, user_id: str, leave_type: str) -> Balance:
        """读取假期余额。

        Args:
            user_id: 用户 ID。
            leave_type: 假期类型。

        Returns:
            Balance: 余额信息，无记录时返回零余额。
        """
        raw = self._state["balances"].get((user_id, leave_type))
        if not raw:
            return Balance(leave_type=leave_type, total=0, used=0, remaining=0)
        return Balance(leave_type=leave_type, **raw)

    def get_approval_route(self, user_id: str, case: LeaveCase) -> ApprovalRoute:
        """读取审批链建议（含无代理人异常注入）。

        Args:
            user_id: 申请人 ID。
            case: 请假单。

        Returns:
            ApprovalRoute: 审批链建议。
        """
        if self.simulate_timeout:
            raise TimeoutError("OA 组织服务超时")
        route_key = case.form_snapshot.get("route_key", "d_rd")
        if self.simulate_route_missing:
            route_key = "d_rd_no_proxy"
        org = self._state["org_routes"].get(route_key, self._state["org_routes"]["d_rd"])
        nodes = [
            ApprovalNode(
                order=n["order"],
                approver_id=n["approver_id"],
                approver_name=n["approver_name"],
                is_proxy=n.get("is_proxy", False),
                proxy_for=n.get("proxy_for"),
                rule_version=org["rule_version"],
            )
            for n in org.get("chain", [])
        ]
        return ApprovalRoute(
            business_id=case.business_id,
            nodes=nodes,
            rule_version=org["rule_version"],
            risk_hint="代理人缺失，需人工确认" if org.get("missing_proxy") else "",
            conflict=bool(org.get("missing_proxy")),
        )

    # ------------------------------------------------------------------ #
    # 写接口（幂等）
    # ------------------------------------------------------------------ #
    def create_or_update_approval(self, command: ApprovalCommand) -> OAResult:
        """创建/更新审批任务（幂等：同一幂等键返回同一结果）。

        Args:
            command: 审批落库命令。

        Returns:
            OAResult: 操作结果。
        """
        key = command.idempotency_key
        persisted = self._state.setdefault("approval_results", {}).get(key)
        if persisted:
            return OAResult(**persisted)
        if key in self._idempotency:
            return self._idempotency[key]
        result = OAResult(
            success=True,
            request_id=f"oa-{key}",
            idempotency_key=key,
            status=command.action,
            payload={"business_id": command.business_id, "approval_id": f"AP-{key[-6:]}"},
        )
        self._idempotency[key] = result
        self._state["approval_results"][key] = result.model_dump()
        self._save_state()
        return result

    def get_approval_result(self, idempotency_key: str) -> OAResult | None:
        persisted = self._state.get("approval_results", {}).get(idempotency_key)
        return OAResult(**persisted) if persisted else None

    def edit_leave_case(self, command: LeaveEditCommand) -> OAResult:
        persisted = self._state.setdefault("leave_edit_results", {}).get(command.idempotency_key)
        if persisted:
            return OAResult(**persisted)
        current = self.get_leave_case(command.business_id)
        if current is None or current.model_dump(mode="json") != command.expected_form.model_dump(mode="json"):
            raise ValueError("OA 请假单已改变，编辑需重新预检")
        updated = LeaveCase.model_validate({**current.model_dump(), **command.fields})
        self._state["leave_cases"][command.business_id] = updated.model_dump(mode="json")
        result = OAResult(success=True, request_id=f"oa-{command.idempotency_key}",
            idempotency_key=command.idempotency_key, status="edited",
            payload={"business_id": command.business_id})
        self._state["leave_edit_results"][command.idempotency_key] = result.model_dump()
        self._save_state()
        return result

    def get_leave_edit_result(self, idempotency_key: str) -> OAResult | None:
        persisted = self._state.get("leave_edit_results", {}).get(idempotency_key)
        return OAResult(**persisted) if persisted else None

    def get_notification_result(self, idempotency_key: str) -> NotificationResult | None:
        if any(item.get("idempotency_key") == idempotency_key for item in self._state["notifications"]):
            return NotificationResult(success=True, delivered=True, request_id=f"ntf-{idempotency_key}",
                idempotency_key=idempotency_key, status="sent")
        return None

    def create_or_merge_ticket(self, command: TicketCommand) -> TicketResult:
        """创建或合并工单（幂等）。

        Args:
            command: 工单命令。

        Returns:
            TicketResult: 操作结果（含 ticket_id）。
        """
        key = command.idempotency_key
        if key in self._idempotency:
            return self._idempotency[key]
        ticket_id = f"TK-{key[-8:]}"
        self._state["tickets"][ticket_id] = {
            "ticket_id": ticket_id,
            "category": command.category,
            "priority": command.priority,
            "summary": command.summary,
            "status": "open",
            "user_id": command.user_id,
        }
        result = TicketResult(
            success=True,
            request_id=f"oa-{key}",
            idempotency_key=key,
            status="open",
            ticket_id=ticket_id,
            payload={"ticket_id": ticket_id},
        )
        self._idempotency[key] = result
        self._save_state()
        return result

    def notify(self, command: NotificationCommand) -> NotificationResult:
        """发送通知（记录发送结果）。

        Args:
            command: 通知命令。

        Returns:
            NotificationResult: 发送结果。
        """
        existing = next((n for n in self._state["notifications"]
                         if command.idempotency_key and n.get("idempotency_key") == command.idempotency_key), None)
        payload = {"user_id": command.user_id, "title": command.title,
                   "body": command.body, "business_id": command.business_id}
        if existing is not None:
            if any(existing.get(key) != value for key, value in payload.items()):
                raise ValueError("同一通知幂等键的内容不能变更")
        else:
            self._state["notifications"].append({**payload, "idempotency_key": command.idempotency_key})
            self._save_state()
        return NotificationResult(
            success=True,
            request_id=f"ntf-{command.idempotency_key or 'x'}",
            idempotency_key=command.idempotency_key,
            status="sent",
            delivered=True,
        )

    def update_leave_case(self, business_id: str, fields: dict) -> None:
        """更新请假单字段（编辑后回写 OA 权威数据）。

        Args:
            business_id: 业务单据号。
            fields: 需更新的字段。
        """
        raw = self._state["leave_cases"].get(business_id)
        if raw:
            raw.update(fields)
            self._save_state()

    def get_ticket_status(self, ticket_id: str) -> Optional[dict]:
        """读取工单状态。

        Args:
            ticket_id: 工单号。

        Returns:
            Optional[dict]: 工单信息，不存在时 None。
        """
        return self._state["tickets"].get(ticket_id)

    def get_field_dict(self) -> dict:
        """返回版本化字段字典（预检规则配置）。

        Returns:
            dict: 字段字典（含规则版本与各假类型字段要求）。
        """
        return self._state["field_dict"]

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """重置到初始状态（测试用）。"""
        self._state = get_initial_state()
        self._idempotency = {}
        self.simulate_timeout = False
        self.simulate_route_missing = False

    def _load_state(self) -> dict:
        """从文件加载状态，失败则回退初始数据。

        Returns:
            dict: 状态字典。
        """
        path = self._settings.mock_state_file
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    balances = state.get("balances", {})
                    state["balances"] = {
                        tuple(key.split("|", 1)): value
                        for key, value in balances.items()
                        if "|" in key
                    }
                    return state
        except Exception:
            pass
        return get_initial_state()

    def _save_state(self) -> None:
        """将状态落盘（失败不影响内存运行）。

        Raises:
            不抛出：落盘失败时静默忽略。
        """
        path = self._settings.mock_state_file
        directory = os.path.dirname(path) or "."
        temp_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            serializable = dict(self._state)
            serializable["balances"] = {
                f"{user_id}|{leave_type}": value
                for (user_id, leave_type), value in self._state.get("balances", {}).items()
            }
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as f:
                temp_path = f.name
                json.dump(serializable, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except Exception:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
