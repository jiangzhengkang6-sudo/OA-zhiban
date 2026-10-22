"""
OA 智能体管理系统 - 预检规则单元测试。

覆盖材料预检的字段/附件/余额/时间冲突四项确定性规则，对应 AC-MVP-01/02。
"""

import pytest

from app.adapters.mock_adapter import MockAdapter
from app.adapters.oa_adapter import LeaveCase
from app.tools import leave_tools


@pytest.fixture
def adapter() -> MockAdapter:
    """提供干净的 Mock 适配器。"""
    a = MockAdapter()
    a.reset()
    return a


def _case(leave_type: str = "annual", reason: str = "家庭事务", attachments=None,
          start="2026-10-13T09:00:00", end="2026-10-14T18:00:00") -> LeaveCase:
    """构造请假单辅助函数。"""
    return LeaveCase(
        business_id="LV-TEST",
        user_id="u_emp_001",
        leave_type=leave_type,
        start_at=start,
        end_at=end,
        reason=reason,
        attachments=attachments or [],
    )


@pytest.mark.asyncio
async def test_validate_form_pass(adapter):
    """材料齐全时应返回全部通过。"""
    results = await leave_tools.validate_leave_form(adapter, _case())
    assert all(r["result"] == "pass" for r in results)


@pytest.mark.asyncio
async def test_validate_form_missing_reason(adapter):
    """缺少必填字段 reason 时应失败并提示。"""
    results = await leave_tools.validate_leave_form(adapter, _case(reason=""))
    field = [r for r in results if r["item"] == "field"][0]
    assert field["result"] == "fail"
    assert "reason" in field["reason"]


@pytest.mark.asyncio
async def test_validate_sick_requires_attachment(adapter):
    """病假需上传证明，缺失附件应失败。"""
    results = await leave_tools.validate_leave_form(
        adapter, _case(leave_type="sick", attachments=[])
    )
    att = [r for r in results if r["item"] == "attachment"][0]
    assert att["result"] == "fail"


def test_check_balance_insufficient():
    """余额不足应失败。"""
    result = leave_tools.check_balance({"remaining": 1}, "annual", 3)
    assert result["result"] == "fail"


def test_check_balance_sufficient():
    """余额充足应通过。"""
    result = leave_tools.check_balance({"remaining": 5}, "annual", 3)
    assert result["result"] == "pass"


def test_check_conflict_end_before_start():
    """结束早于开始应判定为冲突。"""
    case = _case(start="2026-10-15T09:00:00", end="2026-10-14T09:00:00")
    assert leave_tools.check_conflict(case)["result"] == "fail"