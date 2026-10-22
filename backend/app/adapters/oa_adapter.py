"""
OA 智能体管理系统 - OA 适配器契约模块。

本模块定义智能层与现有 OA 系统之间的稳定接口契约（OAAdapter Protocol）及所有跨边界
数据结构（Pydantic 模型）。智能层（LangGraph 节点/工具）只依赖本协议，不直接访问 OA
内部实现，从而隔离"智能编排层"与"权威业务系统"。

MVP 提供 MockAdapter 实现该协议；真实 OA 接口盘点完成后，仅需新增 RealOAAdapter 并
在 factory 中按 OA_PROVIDER 切换，智能层代码无需改动。
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# 跨边界数据结构
# --------------------------------------------------------------------------- #
class UserContext(BaseModel):
    """OA 用户上下文（从 OA 权威读取）。"""

    user_id: str
    tenant_id: str
    name: str
    dept_id: str
    dept_name: str
    roles: list[str] = Field(default_factory=list)
    data_scope: dict[str, Any] = Field(default_factory=dict)


class LeaveCase(BaseModel):
    """OA 请假单快照（OA 为权威）。"""

    business_id: str
    user_id: str
    leave_type: str
    start_at: datetime
    end_at: datetime
    reason: str = ""
    attachments: list[str] = Field(default_factory=list)
    status: str = "DRAFT"
    form_snapshot: dict[str, Any] = Field(default_factory=dict)


class Balance(BaseModel):
    """假期余额。"""

    leave_type: str
    total: float
    used: float
    remaining: float
    unit: str = "day"


class ApprovalNode(BaseModel):
    """审批链候选节点。"""

    order: int
    approver_id: str
    approver_name: str
    is_proxy: bool = False
    proxy_for: str | None = None
    rule_version: str = ""


class ApprovalRoute(BaseModel):
    """审批链建议（由 OA 组织/代理数据裁决）。"""

    business_id: str
    nodes: list[ApprovalNode] = Field(default_factory=list)
    rule_version: str = ""
    risk_hint: str = ""
    conflict: bool = False  # True 表示组织数据冲突，需转人工


class ApprovalCommand(BaseModel):
    """审批落库命令（写工具，HITL 通过后调用）。"""

    business_id: str
    idempotency_key: str
    action: str
    actor_id: str
    comment: str = ""
    route: list[ApprovalNode] = Field(default_factory=list)


class LeaveEditCommand(BaseModel):
    business_id: str
    idempotency_key: str
    actor_id: str
    expected_form: LeaveCase
    fields: dict[str, Any]


class TicketCommand(BaseModel):
    """工单创建/合并命令（写工具，用户确认后调用）。"""

    idempotency_key: str
    category: str
    priority: str
    impact: str
    summary: str
    context: dict[str, Any] = Field(default_factory=dict)
    user_id: str
    queue_id: str = ""
    extracted_fields: dict[str, Any] = Field(default_factory=dict)


class NotificationCommand(BaseModel):
    """通知发送命令（写工具）。"""

    user_id: str
    channel: str = "oa_inbox"  # MVP 复用 OA 站内通知渠道
    title: str
    body: str
    business_id: str = ""
    idempotency_key: str = ""


class OAResult(BaseModel):
    """OA 通用返回结构（带 request_id + 幂等键，便于对账）。"""

    success: bool
    request_id: str
    idempotency_key: str
    status: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class TicketResult(OAResult):
    """工单操作返回结构。"""

    ticket_id: str = ""


class NotificationResult(OAResult):
    """通知发送返回结构。"""

    delivered: bool = False


# --------------------------------------------------------------------------- #
# OAAdapter 协议
# --------------------------------------------------------------------------- #
class OAAdapter(Protocol):
    """OA 适配器协议：智能层访问 OA 权威能力的唯一入口。

    约定：
    1. get_* 为只读，任意场景可调用，但必须在调用前完成权限/范围校验。
    2. create_* / notify 为写操作，必须满足 HITL（人工确认）且带幂等键。
    3. 所有写操作必须幂等：同一 idempotency_key 重复调用返回相同结果，不重复执行。
    """

    def get_user_context(self, user_id: str) -> UserContext:
        """读取用户上下文（身份/部门/角色/数据范围）。

        Args:
            user_id: OA 用户 ID。

        Returns:
            UserContext: 用户上下文。
        """
        ...

    def get_leave_case(self, business_id: str) -> LeaveCase:
        """读取请假单快照。

        Args:
            business_id: 业务单据号。

        Returns:
            LeaveCase: 请假单快照。
        """
        ...

    def get_leave_balance(self, user_id: str, leave_type: str) -> Balance:
        """读取假期余额。

        Args:
            user_id: 用户 ID。
            leave_type: 假期类型。

        Returns:
            Balance: 余额信息。
        """
        ...

    def get_approval_route(self, user_id: str, case: LeaveCase) -> ApprovalRoute:
        """读取审批链建议（以 OA 组织/代理数据为准）。

        Args:
            user_id: 申请人 ID。
            case: 请假单快照。

        Returns:
            ApprovalRoute: 审批链建议。
        """
        ...

    def create_or_update_approval(self, command: ApprovalCommand) -> OAResult:
        """创建/更新 OA 审批任务（写操作，须幂等）。

        Args:
            command: 审批落库命令。

        Returns:
            OAResult: 操作结果。
        """
        ...

    def get_approval_result(self, idempotency_key: str) -> OAResult | None:
        """Look up an uncertain approval write by its original key; never reissue it."""
        ...

    def edit_leave_case(self, command: LeaveEditCommand) -> OAResult:
        """Apply an approved edit only if the authoritative form still matches its precheck."""
        ...

    def get_leave_edit_result(self, idempotency_key: str) -> OAResult | None:
        """Look up a potentially applied form edit without reissuing it."""
        ...

    def get_notification_result(self, idempotency_key: str) -> NotificationResult | None:
        """Look up a potentially delivered notification without resending it."""
        ...

    def create_or_merge_ticket(self, command: TicketCommand) -> TicketResult:
        """创建或合并工单（写操作，须幂等）。

        Args:
            command: 工单命令。

        Returns:
            TicketResult: 操作结果（含 ticket_id）。
        """
        ...

    def notify(self, command: NotificationCommand) -> NotificationResult:
        """发送通知（写操作，复用 OA 通知渠道）。

        Args:
            command: 通知命令。

        Returns:
            NotificationResult: 发送结果。
        """
        ...
