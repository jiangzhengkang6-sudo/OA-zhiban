"""
OA 智能体管理系统 - 工具白名单注册表。

定义每个场景允许调用的工具集合，工具调用前必须经过 is_tool_allowed 校验，
越权工具直接拒绝（对应 PRD 5.3 工具白名单与 AC-MVP 权限隔离）。
"""

from ..core.enums import Scene, ToolName

# 场景 -> 允许工具集合（白名单）
SCENE_TOOLS: dict[str, set[str]] = {
    Scene.WORK_TASK.value: {"extract_work_task_candidates"},
    Scene.REPORT.value: {"run_registered_report_query"},
    Scene.CONTRACT.value: {"write_todos", "read_contract_block"},
    Scene.LEAVE.value: {
        ToolName.GET_USER_CONTEXT.value,
        ToolName.GET_LEAVE_BALANCE.value,
        ToolName.VALIDATE_LEAVE_FORM.value,
        ToolName.GET_APPROVAL_ROUTE.value,
        ToolName.CREATE_OR_UPDATE_OA_APPROVAL.value,
        ToolName.NOTIFY_USER.value,
    },
    Scene.FAQ.value: {
        ToolName.GET_USER_CONTEXT.value,
        ToolName.SEARCH_KNOWLEDGE.value,
        ToolName.NOTIFY_USER.value,
    },
    Scene.TICKET.value: {
        ToolName.GET_USER_CONTEXT.value,
        ToolName.CREATE_OR_MERGE_TICKET.value,
        ToolName.GET_TICKET_STATUS.value,
        ToolName.NOTIFY_USER.value,
    },
}

# 写工具集合（调用前必须 HITL 通过 + 幂等键）
WRITE_TOOLS: set[str] = {
    ToolName.CREATE_OR_UPDATE_OA_APPROVAL.value,
    ToolName.CREATE_OR_MERGE_TICKET.value,
    ToolName.NOTIFY_USER.value,
}


def is_tool_allowed(scene: str, tool_name: str) -> bool:
    """判断某工具在当前场景白名单内。

    Args:
        scene: 业务场景。
        tool_name: 工具名。

    Returns:
        bool: 是否允许调用。
    """
    return tool_name in SCENE_TOOLS.get(scene, set())


def is_write_tool(tool_name: str) -> bool:
    """判断是否为写工具（需 HITL 与幂等）。

    Args:
        tool_name: 工具名。

    Returns:
        bool: 是否为写工具。
    """
    return tool_name in WRITE_TOOLS
