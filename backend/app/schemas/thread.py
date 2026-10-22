"""
OA 智能体管理系统 - 会话相关请求/响应模型。

定义智能助手会话创建、消息发送、状态查询的对外 DTO。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ThreadCreateRequest(BaseModel):
    """创建会话请求。

    Attributes:
        scene: 业务场景（leave/faq/ticket）。
        business_id: 可选业务单据号（如请假单号，幂等用）。
    """

    scene: str = Field(description="业务场景：leave/faq/ticket")
    business_id: Optional[str] = Field(default=None, description="业务单据号")


class ThreadResponse(BaseModel):
    """会话创建响应。

    Attributes:
        thread_id: 会话 ID（也是 LangGraph thread_id）。
        status: 当前状态。
        business_id: 业务单据号。
    """

    thread_id: str
    status: str
    business_id: Optional[str] = None


class MessageCreateRequest(BaseModel):
    """发送消息请求。

    Attributes:
        content: 消息内容。
        idempotency_key: 幂等键（可选，保证不重复处理）。
    """

    content: str
    idempotency_key: Optional[str] = None


class MessageResponse(BaseModel):
    """发送消息响应。

    Attributes:
        message_id: 消息 ID。
        status: 处理后的会话状态。
        trace_id: 本次运行 trace_id。
        next_action: 下一步动作提示。
    """

    message_id: str
    status: str
    trace_id: str = ""
    next_action: Optional[str] = None


class ThreadDetail(BaseModel):
    """会话状态详情。

    Attributes:
        thread_id: 会话 ID。
        scene: 场景。
        status: 状态。
        intent: 意图。
        business_id: 业务单据号。
        next_action: 下一步动作提示。
        messages: 消息列表（摘要）。
        precheck: 预检结果（请假场景）。
        approval_route: 审批链建议。
        human_decision: 最近人工决定。
        answer: FAQ 回答（客服场景）。
        ticket: 工单信息（工单场景）。
        error: 错误信息（暂停场景）。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    thread_id: str
    scene: str
    status: str
    intent: Optional[str] = None
    business_id: Optional[str] = None
    application_id: Optional[str] = None
    current_interrupt_id: Optional[str] = None
    next_action: Optional[str] = None
    messages: list[dict] = Field(default_factory=list)
    precheck: Optional[dict] = None
    form_snapshot: Optional[dict] = None
    approval_route: Optional[dict] = None
    approval_status: Optional[str] = None
    approval_recovery_action: Optional[str] = None
    active_approval_node: Optional[dict] = None
    approval_nodes: list[dict] = Field(default_factory=list)
    approval_decisions: list[dict] = Field(default_factory=list)
    human_decision: Optional[dict] = None
    answer: Optional[dict] = None
    ticket: Optional[dict] = None
    ticket_fields: Optional[dict] = None
    ticket_draft: Optional[dict] = None
    ticket_candidates: list[dict] = Field(default_factory=list)
    ticket_review: Optional[dict] = None
    handoff: Optional[dict] = None
    error: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
