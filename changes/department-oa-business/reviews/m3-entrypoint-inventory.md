# M3 B5 正式入口盘点

更新：2026-10-20。此表记录 B5 已核对的正式业务入口；逐项证据见 [能力矩阵](m3-capability-matrix.md)、[六场景矩阵](m3-six-scene-matrix.md)。旧 Mock/legacy 入口不因存在而成为 builtin 权威。

| 范围 | 入口 | 当前边界 | B5 处理 |
| --- | --- | --- | --- |
| 内桥 | `adapters/builtin_gateway.py` | `BridgeContext` 携带 actor/session/trace/confirmation；未开放能力返回 503 | 13 核心及 2 辅助能力逐项映射；必需能力有成功路径，禁止同步无上下文调用 |
| 知识 | `api/routers/knowledge.py`、`tools/knowledge_tools.py`、`graph/nodes/faq_nodes.py` | 正式版本、租户绑定、所有者/部门范围；生成前复核 | 0028、正式绑定与检索前过滤已完成 |
| 策略 | `api/routers/policies.py`、`services/policy_version_service.py` | 旧策略不作为 builtin 权威；正式策略版本需租户归属 | 0028 正式表、租户/部门/用户发布写入和读取已接入 |
| 审计 | `services/audit_service.py`、`api/routers/audit.py`、`api/routers/audit_export.py` | 正式审计记录需资源、对象、部门和租户 | 正式写入、列表、导出均按租户/部门范围过滤 |
| P2 文档/邮件/会议 | 对应 `document_service`、`email_service`、`meeting_service` | 详情/版本/预览、生成和重放复核最新身份、部门及来源 | 文档绑定撤销、三场景调岗、异步成功/异常分支、会议确认均有测试；无独立文件导出路由 |
| P3 任务/报表/合同 | `work_task_service`、`report_service/query`、`contract_service` | 派生、聚合、快照及重放复核来源；合同限本人/指定审核人 | 正式工单/请假/报销来源、部门报表与来源权限交集、参与人隔离和缓存重放已验证；无独立文件导出路由 |
| 图与恢复 | `graph/nodes/*`、`graph/graph_service.py`、`interrupts` | 恢复前最新身份、来源和领域权威结果 | FAQ/请假/工单含真实登录和 PostgreSQL 运行时关闭重建；原键只读对账，不补发写入 |
| 后台与调度 | `scheduler.py`、`work_task_scheduler.py` | AI 关闭仍扫描正式流程、通知和已创建工作任务；失权来源停止提醒 | 修复 builtin 工作任务扫描遗漏，四组身份/AI 分支及实际主循环已验证；不自动删除已有本人任务 |

## 旧适配器调用盘点

以下文件保留同步 legacy 调用。正式业务采用独立 builtin 分支或依赖门禁，不经这些同步调用执行正式写入：

- `graph/nodes/common.py`
- `graph/nodes/leave_nodes.py`
- `services/approval_service.py`
- `services/ticket_service.py`
- `services/thread_service.py`
- `services/scheduler.py`
- `api/routers/approvals.py`
- `api/routers/tickets.py`

正式图和工具从依赖层取得可信 `CurrentUser`，通过 `BuiltinGateway(BridgeContext(...))` 异步调用；人工 `/api/oa/*` 直接调用同一正式领域服务。无法获得确认或能力时明确拒绝，不转 Mock。必需能力不能用 503 代替交付。运营管理等未纳入本次逐入口开放的模块仍保留拒绝，不能表述为全站正式化。
