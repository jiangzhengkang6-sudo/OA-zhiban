"""统一助手 V3 的技能路由测试。"""

from app.services.assistant_v3_service import classify


def test_leave_policy_question_routes_to_knowledge():
    assert classify("请假申请应该怎么办理？", "auto")[0] == "knowledge"


def test_explicit_leave_request_routes_to_leave():
    assert classify("我想明天请一天年假", "auto")[0] == "leave"


def test_repair_question_routes_to_knowledge():
    assert classify("电脑故障如何报修？", "auto")[0] == "knowledge"


def test_explicit_repair_request_routes_to_ticket():
    assert classify("我的电脑无法开机，帮我报修", "auto")[0] == "ticket"


def test_meeting_request_routes_to_meeting():
    assert classify("明天下午3点和李四开项目复盘会", "auto")[0] == "meeting"


def test_recurring_reminder_routes_to_task():
    assert classify("每天早上9点提醒我检查日报", "auto")[0] == "task"


def test_reports_and_overview_routing():
    assert classify("帮我生成一份周报", "auto")[0] == "report"
    assert classify("给我今天的工作总览", "auto")[0] == "overview"


def test_explicit_human_routing():
    assert classify("转人工", "auto")[0] == "human"

