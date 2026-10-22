"""
OA 智能体管理系统 - 全局枚举定义模块。

本模块是全局契约的源头，集中定义场景(Scene)、意图(Intent)、会话状态(ThreadStatus)、
人工动作(HumanAction)、工具名称(ToolName)、预检项与结果、审计动作、知识文档状态、
工单状态等枚举。所有枚举统一继承 str+Enum，以便：
1. 与数据库 VARCHAR 列直接对应（无需额外 ENUM 类型迁移）；
2. 可被 Pydantic 校验、JSON 序列化；
3. 前后端通过字符串对齐契约。

修改本文件等同于修改系统契约，需同步更新前端 types 与数据库 CHECK 约束。
"""

from enum import Enum


class Scene(str, Enum):
    """业务场景：智能层支持的三类场景。"""

    LEAVE = "leave"      # 智能请假审批
    FAQ = "faq"          # 客服知识问答
    TICKET = "ticket"    # 工单办理
    MEETING = "meeting"  # 会议文本整理
    DOCUMENT = "document"
    EMAIL = "email"
    WORK_TASK = "work_task"
    REPORT = "report"
    CONTRACT = "contract"


class Intent(str, Enum):
    """SuperAgent 识别的用户意图。"""

    LEAVE = "leave"      # 请假/审批
    FAQ = "faq"          # 制度咨询/问答
    TICKET = "ticket"    # 工单办理
    HUMAN = "human"      # 转人工
    UNKNOWN = "unknown"  # 未知意图
    MEETING = "meeting"  # 会议文本整理


class MeetingStatus(str, Enum):
    """会议文本智能体状态。"""

    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    DRAFT_READY = "DRAFT_READY"
    REVIEWING = "REVIEWING"
    PAUSED = "PAUSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class MeetingDecisionAction(str, Enum):
    """人工会议草稿决定。"""

    CONFIRM = "confirm"
    REJECT = "reject"
    REGENERATE = "regenerate"


class ThreadStatus(str, Enum):
    """会话/任务的编排状态机（对应 PRD 4.7 状态模型）。"""

    DRAFT = "DRAFT"                    # 草稿或自然语言待确认
    PRECHECK = "PRECHECK"              # 正在预检
    NEEDS_FIX = "NEEDS_FIX"            # 缺项，等待用户修改
    ROUTING = "ROUTING"                # 计算审批链/分派建议
    WAITING_HUMAN = "WAITING_HUMAN"    # 等待人工审批/客服决策
    ESCALATED = "ESCALATED"            # 已升级
    APPROVED = "APPROVED"              # 已批准/已由 OA 执行
    REJECTED = "REJECTED"              # 已驳回
    PAUSED = "PAUSED"                  # 依赖故障/降级暂停
    COMPLETED = "COMPLETED"            # 终态完成


class HumanAction(str, Enum):
    """HITL 人工决定动作。"""

    APPROVE = "approve"    # 批准
    EDIT = "edit"          # 编辑后批准
    REJECT = "reject"      # 驳回
    CONFIRM = "confirm"    # 确认（如工单草稿确认）
    CANCEL = "cancel"      # 取消
    ESCALATE = "escalate"  # 升级（系统动作）


class ToolName(str, Enum):
    """工具白名单中的工具标识（对应 PRD 5.3 工具白名单）。"""

    GET_USER_CONTEXT = "get_user_context"
    GET_LEAVE_BALANCE = "get_leave_balance"
    VALIDATE_LEAVE_FORM = "validate_leave_form"
    GET_APPROVAL_ROUTE = "get_approval_route"
    CREATE_OR_UPDATE_OA_APPROVAL = "create_or_update_oa_approval"
    SEARCH_KNOWLEDGE = "search_knowledge"
    CREATE_OR_MERGE_TICKET = "create_or_merge_ticket"
    GET_TICKET_STATUS = "get_ticket_status"
    NOTIFY_USER = "notify_user"


class PrecheckItem(str, Enum):
    """请假设检项类型。"""

    FIELD = "field"            # 必填字段
    ATTACHMENT = "attachment"  # 附件完整性
    BALANCE = "balance"        # 假期余额
    CONFLICT = "conflict"      # 时间冲突


class PrecheckResult(str, Enum):
    """单条预检判定结果。"""

    PASS = "pass"
    FAIL = "fail"


class AuditAction(str, Enum):
    """审计事件动作类型（对应 PRD 8.2 审计要求）。"""

    SESSION_CREATED = "session_created"
    INTENT_ROUTED = "intent_routed"
    TOOL_CALLED = "tool_called"
    PRECHECK_RESULT = "precheck_result"
    KNOWLEDGE_RETRIEVED = "knowledge_retrieved"
    MODEL_ANSWERED = "model_answered"
    HUMAN_DECIDED = "human_decided"
    BUSINESS_WRITE = "business_write"
    NOTIFICATION_SENT = "notification_sent"
    RETRIED = "retried"
    ERROR_OCCURRED = "error_occurred"
    POLICY_CHANGED = "policy_changed"
    DEGRADED = "degraded"


class KnowledgeDocStatus(str, Enum):
    """知识文档生命周期状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    EXPIRED = "expired"
    OFFLINE = "offline"


class TicketStatus(str, Enum):
    """工单状态。"""

    OPEN = "open"              # 待处理
    IN_PROGRESS = "in_progress"  # 处理中
    RESOLVED = "resolved"      # 已解决
    CLOSED = "closed"          # 已关闭


class ErrorCode(str, Enum):
    """统一错误码（字符串形式，前后端对齐）。"""

    OK = "0"
    BAD_REQUEST = "10001"                 # 参数校验错误
    UNAUTHORIZED = "40101"                # 未认证
    FORBIDDEN = "40301"                   # 无权限
    TOOL_NOT_ALLOWED = "40302"            # 工具白名单拒绝
    NOT_FOUND = "40401"                   # 资源不存在
    INTERRUPT_NOT_FOUND = "40402"         # 中断不存在
    IDEMPOTENCY_CONFLICT = "40901"        # 幂等冲突/重复提交
    INTERRUPT_ALREADY_HANDLED = "40902"   # 中断已处理
    INVALID_STATE = "42201"               # 业务状态不允许
    DEPENDENCY_FAILED = "50201"           # OA 依赖失败（暂停）
    INTERNAL_ERROR = "50001"              # 内部错误
    DEGRADED = "50301"                    # 智能层降级
    MEETING_INPUT_INVALID = "10011"         # 会议文本无效
    MEETING_CONTENT_TOO_LONG = "10012"      # 会议文本超长
