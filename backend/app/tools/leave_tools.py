"""
OA 智能体管理系统 - 请假相关工具。

提供请假预检所需的确定性工具：字段/附件校验（validate_leave_form，代码规则不调用
模型）、余额读取（get_leave_balance）、审批链建议读取（get_approval_route）。
"""

from datetime import datetime
from typing import Any

from ..adapters.oa_adapter import OAAdapter, LeaveCase
from ..core.enums import PrecheckItem


async def get_leave_balance(adapter: OAAdapter, user_id: str, leave_type: str) -> dict:
    """读取假期余额。

    Args:
        adapter: OA 适配器。
        user_id: 用户 ID。
        leave_type: 假期类型。

    Returns:
        dict: 余额信息（leave_type/total/used/remaining/unit）。
    """
    balance = adapter.get_leave_balance(user_id, leave_type)
    return balance.model_dump()


async def get_approval_route(adapter: OAAdapter, user_id: str, case: LeaveCase) -> dict:
    """读取审批链建议。

    Args:
        adapter: OA 适配器。
        user_id: 申请人 ID。
        case: 请假单。

    Returns:
        dict: 审批链建议（nodes/rule_version/risk_hint/conflict）。
    """
    route = adapter.get_approval_route(user_id, case)
    return route.model_dump()


async def validate_leave_form(adapter: OAAdapter, case: LeaveCase) -> list[dict]:
    """校验必填字段与附件完整性（确定性代码规则）。

    Args:
        adapter: OA 适配器（用于读取版本化字段字典）。
        case: 请假单。

    Returns:
        list[dict]: 字段/附件校验结果列表，每项含 item/result/reason/suggestion。
    """
    field_dict = adapter.get_field_dict()
    results: list[dict] = []
    leave_type = case.leave_type
    type_cfg = field_dict["leave_types"].get(leave_type, {})

    # 1. 字段校验
    required_fields = type_cfg.get("required_fields", [])
    present = _case_to_fields(case)
    missing = [f for f in required_fields if not present.get(f)]
    if missing:
        results.append(
            {
                "item": PrecheckItem.FIELD.value,
                "result": "fail",
                "reason": f"缺少必填字段：{', '.join(missing)}",
                "suggestion": "请补充缺失字段后重新提交",
            }
        )
    else:
        results.append(
            {"item": PrecheckItem.FIELD.value, "result": "pass", "reason": "必填字段齐全"}
        )

    # 2. 附件校验
    attachment_required = type_cfg.get("attachment_required", False)
    attachments = case.attachments or []
    if attachment_required and not attachments:
        results.append(
            {
                "item": PrecheckItem.ATTACHMENT.value,
                "result": "fail",
                "reason": f"{leave_type} 类型请假需上传证明材料",
                "suggestion": "请上传必要的证明材料附件",
            }
        )
    else:
        results.append(
            {"item": PrecheckItem.ATTACHMENT.value, "result": "pass", "reason": "附件齐全"}
        )

    return results


def check_balance(
    balance: dict, leave_type: str, days: float
) -> dict:
    """校验假期余额是否充足。

    Args:
        balance: 余额信息（含 remaining）。
        leave_type: 假期类型。
        days: 申请天数。

    Returns:
        dict: 预检结果（item=balance）。
    """
    remaining = float(balance.get("remaining", 0))
    if remaining >= days:
        return {
            "item": PrecheckItem.BALANCE.value,
            "result": "pass",
            "reason": f"余额充足（剩余 {remaining}）",
        }
    return {
        "item": PrecheckItem.BALANCE.value,
        "result": "fail",
        "reason": f"{leave_type} 余额不足（剩余 {remaining}，申请 {days}）",
        "suggestion": "请减少申请天数或改用其他假期类型",
    }


def check_conflict(case: LeaveCase) -> dict:
    """校验日期合法性与时间冲突。

    Args:
        case: 请假单。

    Returns:
        dict: 预检结果（item=conflict）。
    """
    try:
        start = _parse(case.start_at)
        end = _parse(case.end_at)
    except (TypeError, ValueError):
        return {
            "item": PrecheckItem.CONFLICT.value,
            "result": "fail",
            "reason": "日期格式非法",
            "suggestion": "请检查开始/结束日期",
        }
    if end <= start:
        return {
            "item": PrecheckItem.CONFLICT.value,
            "result": "fail",
            "reason": "结束日期必须晚于开始日期",
            "suggestion": "请修改请假时间段",
        }
    return {
        "item": PrecheckItem.CONFLICT.value,
        "result": "pass",
        "reason": "日期合法且无冲突",
    }


def compute_days(case: LeaveCase) -> float:
    """计算请假天数（按自然日，含首尾）。

    Args:
        case: 请假单。

    Returns:
        float: 请假天数。
    """
    try:
        start = _parse(case.start_at)
        end = _parse(case.end_at)
    except (TypeError, ValueError):
        return 0.0
    return max((end - start).days + 1, 0)


def _case_to_fields(case: LeaveCase) -> dict[str, Any]:
    """将请假单展开为字段字典（合并 form_snapshot）。

    Args:
        case: 请假单。

    Returns:
        dict[str, Any]: 字段名 -> 值。
    """
    fields: dict[str, Any] = {
        "leave_type": case.leave_type,
        "start_at": case.start_at,
        "end_at": case.end_at,
        "reason": case.reason,
        "attachments": case.attachments,
    }
    fields.update(case.form_snapshot or {})
    return fields


def _parse(value) -> datetime:
    """解析日期时间值（支持 datetime/str）。

    Args:
        value: 日期时间或 ISO 字符串。

    Returns:
        datetime: 解析结果。

    Raises:
        ValueError: 无法解析时。
    """
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))