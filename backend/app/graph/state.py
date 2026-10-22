"""
OA 智能体管理系统 - LangGraph 状态对象定义。

使用 TypedDict 定义各子图状态，节点间仅传递强类型字段（内嵌 dict 均对应 Pydantic
可校验结构），messages 通过 Annotated[list, operator.add] 累积。核心 AgentState 字段
见各 key 注释；LeaveState/FaqState/TicketState 在各自场景扩展。
"""

import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    """SuperAgent 顶层通用状态。

    Attributes:
        thread_id: 会话 ID（= LangGraph thread_id）。
        user_id: OA 用户 ID。
        tenant_id: 租户 ID。
        trace_id: 一次运行追踪 ID。
        scene: 业务场景。
        intent: 识别意图。
        intent_confidence: 意图置信度。
        business_id: 业务单据号。
        permissions: 权限快照（dict）。
        policy: 生效策略/阈值快照（dict）。
        messages: 消息列表（累积）。
        tool_results: 工具调用结果列表。
        precheck: 预检结果（dict）。
        approval_route: 审批链建议（dict）。
        human_decision: 人工决定（dict）。
        faq_chunks: FAQ 命中切片（list[dict]）。
        answer: FAQ 回答（dict）。
        ticket_fields: 工单抽取字段（dict）。
        ticket: 已创建工单摘要（dict）。
        next_action: 下一步动作提示。
        error: 错误信息（dict）。
    """

    thread_id: str
    user_id: str
    tenant_id: str
    trace_id: str
    scene: str
    intent: str
    intent_confidence: float
    business_id: str | None
    permissions: dict
    policy: dict
    messages: Annotated[list[dict], operator.add]
    tool_results: list[dict]
    precheck: dict | None
    form_snapshot: dict | None
    approval_route: dict | None
    human_decision: dict | None
    faq_chunks: list[dict]
    answer: dict | None
    ticket_fields: dict | None
    ticket_draft: dict | None
    handoff: dict | None
    ticket: dict | None
    next_action: str
    error: dict | None

    # Meeting fields must also live in the parent schema so child output survives.
    title: str
    content: str
    source_type: str
    segments: list[dict]
    draft: dict | None
    meeting_status: str
    meeting_version: int
    meeting_command_key: str
    meeting_decision_key: str
    meeting_generation_action: str


class LeaveState(AgentState, total=False):
    """请假审批子图状态（扩展表单快照）。"""

    form_snapshot: dict
    leave_confirmation_id: str


class FaqState(AgentState, total=False):
    """FAQ 问答子图状态（扩展检索结果）。"""

    question: str


class TicketState(AgentState, total=False):
    """工单子图状态（扩展确认动作）。"""

    confirmation: dict | None


class MeetingState(AgentState, total=False):
    """会议文本子图状态，确认结果仅保存在平台内。"""

    pass
