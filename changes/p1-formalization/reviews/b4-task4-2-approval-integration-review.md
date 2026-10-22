# B4 Task 4.2 审批接入审查

日期：2026-10-12

## 范围

- 内置请假预检通过后创建稳定 `AgentThread`。
- 申请与任务线程通过 `thread_id` 关联，并以 `0006_builtin_leave_thread` 迁移扩展。
- 使用现有组织路由和 `ApprovalService` 创建正式审批实例与有序节点。
- 新增内置审批决定入口，复用当前节点校验、幂等与逐级推进。
- 预检失败不创建线程或审批实例；`LA-*` 不再被当作 Mock OA 外部单号查询。

## 验证

```text
python -m pytest tests/api/test_builtin_leave_flow.py -q
5 passed

ALLOW_TEST_DATABASE_RESET=true python -m pytest tests/migrations tests/api tests/graph tests/unit -q
117 passed in 23.12s
```

## 结论

通过。Task 4.2 的后端审批接入完成。尚未覆盖页面工作台、真实附件内容存储/病毒扫描及完整驳回重提页面验收。
