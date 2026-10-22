"""
OA 智能体管理系统 - Mock OA 数据集模块。

为 MockAdapter 提供权威的静态业务数据与版本化字段字典，覆盖正常与异常边界用例
（材料齐全/缺附件/缺字段/余额不足/时间冲突/无代理人/超时等），用于开发与测试阶段
跑通两个业务闭环。真实 OA 接入后本模块不再参与生产运行。
"""

from datetime import datetime, timedelta
from copy import deepcopy

# --------------------------------------------------------------------------- #
# 账号（员工/审批人/二级审批人/客服/管理员）
# --------------------------------------------------------------------------- #
MOCK_USERS = {
    "u_emp_001": {
        "user_id": "u_emp_001",
        "tenant_id": "t_001",
        "name": "张三",
        "dept_id": "d_rd",
        "dept_name": "研发部",
        "roles": ["employee"],
        "data_scope": {"dept": "d_rd", "self_only": True},
    },
    "u_mgr_001": {
        "user_id": "u_mgr_001",
        "tenant_id": "t_001",
        "name": "李四",
        "dept_id": "d_rd",
        "dept_name": "研发部",
        "roles": ["approver"],
        "data_scope": {"dept": "d_rd"},
    },
    "u_mgr_002": {
        "user_id": "u_mgr_002",
        "tenant_id": "t_001",
        "name": "王五",
        "dept_id": "d_rd",
        "dept_name": "研发部",
        "roles": ["approver"],
        "data_scope": {"dept": "d_rd"},
    },
    "u_cs_001": {
        "user_id": "u_cs_001",
        "tenant_id": "t_001",
        "name": "赵六",
        "dept_id": "d_ops",
        "dept_name": "客服部",
        "roles": ["cs"],
        "data_scope": {"dept": "d_ops"},
    },
    "u_cs_002": {
        "user_id": "u_cs_002",
        "tenant_id": "t_001",
        "name": "客服乙",
        "dept_id": "d_ops",
        "dept_name": "客服部",
        "roles": ["cs"],
        "data_scope": {"dept": "d_ops"},
    },
    "u_admin_001": {
        "user_id": "u_admin_001",
        "tenant_id": "t_001",
        "name": "管理员",
        "dept_id": "d_ops",
        "dept_name": "运营部",
        "roles": ["admin"],
        "data_scope": {"all": True},
    },
}

# --------------------------------------------------------------------------- #
# 假期余额（user_id, leave_type -> 余额）
# --------------------------------------------------------------------------- #
MOCK_BALANCES = {
    ("u_emp_001", "annual"): {"total": 10.0, "used": 3.0, "remaining": 7.0},
    ("u_emp_001", "sick"): {"total": 5.0, "used": 5.0, "remaining": 0.0},
    ("u_emp_001", "personal"): {"total": 3.0, "used": 1.0, "remaining": 2.0},
    ("u_emp_002", "annual"): {"total": 10.0, "used": 0.0, "remaining": 10.0},
}

# --------------------------------------------------------------------------- #
# 版本化字段字典（Q2 决策：确定性规则优先）
# --------------------------------------------------------------------------- #
LEAVE_FIELD_DICT = {
    "rule_version": "v1",
    "leave_types": {
        "annual": {
            "required_fields": ["leave_type", "start_at", "end_at", "reason"],
            "attachment_required": False,
        },
        "sick": {
            "required_fields": ["leave_type", "start_at", "end_at", "reason"],
            "attachment_required": True,  # 病假需上传证明
        },
        "personal": {
            "required_fields": ["leave_type", "start_at", "end_at"],
            "attachment_required": False,
        },
    },
}

# --------------------------------------------------------------------------- #
# 组织审批链（部门 -> 候选审批链；含代理与无代理人异常样例）
# --------------------------------------------------------------------------- #
MOCK_ORG_ROUTES = {
    "d_rd": {
        "rule_version": "org-v1",
        "chain": [
            {"order": 1, "approver_id": "u_mgr_001", "approver_name": "李四", "is_proxy": False},
            {"order": 2, "approver_id": "u_mgr_002", "approver_name": "王五", "is_proxy": False},
        ],
    },
    "d_rd_no_proxy": {  # 无代理人异常样例：升级时无法获取代理人
        "rule_version": "org-v1",
        "chain": [
            {"order": 1, "approver_id": "u_mgr_missing", "approver_name": "待定", "is_proxy": False},
        ],
        "missing_proxy": True,
    },
}

# --------------------------------------------------------------------------- #
# 请假单边界样例
# --------------------------------------------------------------------------- #
_NOW = datetime(2026, 10, 12, 9, 0, 0)


def _leave(business_id: str, **overrides) -> dict:
    """构造一条请假单样例并合并覆盖项。

    Args:
        business_id: 业务单据号。
        **overrides: 覆写字段。

    Returns:
        dict: 请假单字典。
    """
    base = {
        "business_id": business_id,
        "user_id": "u_emp_001",
        "leave_type": "annual",
        "start_at": (_NOW + timedelta(days=1)).isoformat(),
        "end_at": (_NOW + timedelta(days=2)).isoformat(),
        "reason": "家庭事务",
        "attachments": [],
        "status": "DRAFT",
        "form_snapshot": {},
    }
    base.update(overrides)
    return base


MOCK_LEAVE_CASES = {
    # 正常年假（材料齐全）
    "LV-OK-001": _leave("LV-OK-001"),
    # 缺附件（病假需证明）
    "LV-NOATT-001": _leave(
        "LV-NOATT-001", leave_type="sick",
        start_at=(_NOW + timedelta(days=3)).isoformat(),
        end_at=(_NOW + timedelta(days=4)).isoformat(),
        reason="感冒就医",
    ),
    # 缺必填字段（无 reason）
    "LV-NOFIELD-001": _leave("LV-NOFIELD-001", reason=""),
    # 余额不足
    "LV-NOBAL-001": _leave(
        "LV-NOBAL-001", leave_type="sick",
        start_at=(_NOW + timedelta(days=5)).isoformat(),
        end_at=(_NOW + timedelta(days=5, hours=8)).isoformat(),
        reason="复查",
        attachments=["proof.pdf"],
    ),
    # 时间冲突（end < start）
    "LV-CONFLICT-001": _leave(
        "LV-CONFLICT-001",
        start_at=(_NOW + timedelta(days=9)).isoformat(),
        end_at=(_NOW + timedelta(days=8)).isoformat(),
    ),
}

# --------------------------------------------------------------------------- #
# 工单队列
# --------------------------------------------------------------------------- #
MOCK_QUEUES = {
    "q_it": {"queue_id": "q_it", "name": "IT 支持队列", "assignee_id": "u_cs_001"},
    "q_hr": {"queue_id": "q_hr", "name": "HR 队列", "assignee_id": "u_cs_001"},
}

MOCK_TICKETS = {}


def get_initial_state() -> dict:
    """返回 MockAdapter 启动时的初始状态集合（可持久化为 mock_state.json）。

    Returns:
        dict: 包含 users/balances/leave_cases/routes/tickets 的初始状态。
    """
    return deepcopy({
        "users": MOCK_USERS,
        "balances": MOCK_BALANCES,
        "leave_cases": MOCK_LEAVE_CASES,
        "org_routes": MOCK_ORG_ROUTES,
        "queues": MOCK_QUEUES,
        "tickets": MOCK_TICKETS,
        "notifications": [],
        "field_dict": LEAVE_FIELD_DICT,
    })
