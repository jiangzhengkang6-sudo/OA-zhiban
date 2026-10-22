"""Registered metric definitions; source identifiers stay inside private snapshots."""
METRICS = {
    "ticket_volume": {"metric_id": "ticket_volume", "version": 1, "name": "工单量", "unit": "条",
        "definition": "统计区间内创建的内置工单数量，按创建日分组", "source": "ticket_record", "time_field": "created_at"},
    "approval_outcomes": {"metric_id": "approval_outcomes", "version": 1, "name": "审批结果", "unit": "件",
        "definition": "统计区间内创建的审批实例数量，结果取查询时状态；同一业务的不同审批版本分别计数",
        "source": "approval_instance", "time_field": "created_at"},
    "work_task_progress": {"metric_id": "work_task_progress", "version": 1, "name": "任务进展", "unit": "项",
        "definition": "统计区间内创建的业务任务数量，进展取查询时状态；普通用户限创建或负责的任务",
        "source": "work_task", "time_field": "created_at"},
}
ANOMALY_RULE = {"version": 1, "method": "relative_change", "threshold_percent": 50,
                "definition": "仅前期非零时计算变化率，绝对变化至少 50% 为异常候选；原因未证实"}
