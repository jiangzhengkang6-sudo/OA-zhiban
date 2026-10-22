# P1 正式化升级实施任务

## Execution Rules

1. 严格按 B1 → B8 执行；未满足依赖、测试和人工验收的批次不得开始后续批次。
2. 每批开始前报告目标、文件、数据/API/UI 变化、风险和验证方式。B4～B8 含新增功能，必须取得用户明确确认后才能修改实现文件。
3. 每个任务遵循五阶段：Red（写失败测试）→ Red Verify（确认失败原因）→ Green（最小实现）→ Green Verify（通过相关测试）→ Refactor（清理并全量回归）。下列原子步骤预期均为 2～5 分钟。
4. 集成测试只能连接名称以 `_test` 结尾、`ENVIRONMENT=test` 且显式允许清理的数据库。
5. 数据库变更只通过 Alembic；不得清空开发库，不得用 `create_all` 模拟生产升级。
6. 每批结束更新 `docs/manual-verification.md`，保留自动测试输出和手动验收结果。

## File Structure

以下是本变更预计创建或修改的文件。实施时若发现必须增加文件，须先更新本任务文档并在批次报备中说明。

### B1 正式化底座

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/alembic.ini` | Alembic 命令与迁移目录配置 |
| Create | `backend/migrations/env.py` | 加载 ORM metadata 和数据库 URL |
| Create | `backend/migrations/script.py.mako` | 迁移模板 |
| Create | `backend/migrations/versions/0001_mvp_baseline.py` | 当前 MVP 表结构基线 |
| Create | `backend/migrations/versions/0002_command_and_runtime_foundation.py` | 幂等、运行轨迹与兼容字段扩张迁移 |
| Create | `backend/app/models/idempotency_record.py` | 统一副作用幂等记录 |
| Create | `backend/app/models/runtime_span.py` | 节点、工具和模型运行 Span |
| Create | `backend/app/schemas/command.py` | `CommandEnvelope` 与统一写入结果契约 |
| Create | `backend/app/services/idempotency_service.py` | 幂等键、载荷哈希、结果复用和冲突处理 |
| Create | `backend/app/services/authorization_service.py` | 资源授权和调用时权限复核 |
| Create | `backend/app/providers/base.py` | 能力声明、Provider 协议和领域错误 |
| Create | `backend/app/providers/bundle.py` | builtin/mock/real Provider 组装和能力探测 |
| Create | `backend/tests/unit/test_idempotency_service.py` | 幂等单元测试 |
| Create | `backend/tests/unit/test_authorization_service.py` | 资源授权单元测试 |
| Create | `backend/tests/unit/test_provider_bundle.py` | Provider 能力探测测试 |
| Create | `backend/tests/migrations/test_mvp_upgrade.py` | MVP 数据非破坏升级测试 |
| Modify | `backend/app/core/config.py` | 增加认证/Provider/测试安全配置 |
| Modify | `backend/app/core/errors.py` | 统一幂等、能力、暂停和状态错误 |
| Modify | `backend/app/core/enums.py` | 增加命令、Span 与授权相关枚举 |
| Modify | `backend/app/db/base.py` | 迁移使用的统一 metadata |
| Modify | `backend/app/main.py` | 移除生产 `create_all`，加入就绪检查 |
| Modify | `backend/app/models/__init__.py` | 注册新模型 |
| Modify | `backend/app/middleware/auth.py` | 限制 Mock 认证环境并接授权上下文 |
| Modify | `backend/app/adapters/oa_adapter.py` | 兼容 facade 的领域 DTO 对齐 |
| Modify | `backend/app/adapters/factory.py` | 转由 ProviderBundle 选择实现 |
| Modify | `backend/tests/conftest.py` | 测试数据库三重安全闸门 |
| Modify | `backend/.env.example` | 声明环境、认证和 Provider 配置 |

### B2 现有请假流纠正

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/models/approval_instance.py` | 审批实例总体状态与外部引用 |
| Create | `backend/app/models/approval_node.py` | 有序审批节点和当前责任人 |
| Create | `backend/app/models/approval_decision.py` | 节点决定、编辑差异和幂等引用 |
| Create | `backend/app/services/approval_service.py` | 当前节点校验、逐级推进、驳回和恢复 |
| Create | `backend/app/schemas/approval_v2.py` | 审批详情、节点和结构化决定契约 |
| Create | `backend/migrations/versions/0003_approval_instances.py` | 审批实例/节点/决定扩张与旧数据映射 |
| Create | `backend/tests/unit/test_approval_state_machine.py` | 合法/非法节点迁移测试 |
| Create | `backend/tests/api/test_approval_permissions.py` | 越级、并发、编辑和幂等 API 测试 |
| Modify | `backend/app/api/routers/interrupts.py` | 旧 resume 接口转调 ApprovalService |
| Modify | `backend/app/services/interrupt_service.py` | 兼容旧中断并停止直接结束全流程 |
| Modify | `backend/app/services/scheduler.py` | 按活动节点催办、升级和幂等通知 |
| Modify | `backend/app/graph/nodes/leave_nodes.py` | 审批创建/恢复通过领域服务执行 |
| Modify | `backend/app/repositories/thread_repo.py` | 事务内状态条件更新 |
| Modify | `backend/app/schemas/interrupt.py` | 结构化编辑数据和决定幂等键 |
| Modify | `backend/app/models/human_decision.py` | 保留旧数据并关联正式决定 |
| Modify | `frontend/src/components/ApprovalCard.vue` | 编辑后批准表单和当前节点约束 |
| Modify | `frontend/src/views/LeaveDetailView.vue` | 展示活动节点、历史决定和错误状态 |
| Modify | `frontend/src/types/index.ts` | 对齐正式审批契约 |
| Modify | `frontend/src/api/index.ts` | 提交结构化决定和幂等键 |
| Modify | `backend/tests/graph/test_leave_flow.py` | 多级审批与暂停恢复回归 |
| Modify | `backend/tests/api/test_http_flow.py` | 当前 MVP 流程兼容回归 |

### B3 现有 FAQ/工单纠正

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/models/human_queue_item.py` | 正式人工接管队列项 |
| Create | `backend/app/models/handoff_snapshot.py` | 不可覆盖的脱敏交接快照 |
| Create | `backend/app/models/ticket_draft.py` | 用户确认前的可编辑工单草稿 |
| Create | `backend/app/services/handoff_service.py` | 人工交接幂等创建和读取授权 |
| Create | `backend/app/services/ticket_draft_service.py` | 草稿修改、校验和确认 |
| Create | `backend/app/schemas/handoff.py` | 交接包和队列摘要契约 |
| Create | `backend/app/schemas/ticket_draft.py` | 工单草稿字段和确认命令 |
| Create | `backend/migrations/versions/0004_handoff_and_ticket_draft.py` | 人工队列、快照和草稿表 |
| Create | `backend/tests/unit/test_handoff_service.py` | 交接幂等和脱敏测试 |
| Create | `backend/tests/api/test_ticket_draft_flow.py` | 草稿修改、确认和权限测试 |
| Modify | `backend/app/graph/nodes/faq_nodes.py` | 未命中/故障创建人工交接项 |
| Modify | `backend/app/graph/nodes/ticket_nodes.py` | 抽取结果保存草稿，确认后才写工单 |
| Modify | `backend/app/api/routers/tickets.py` | 草稿修改/确认兼容入口 |
| Modify | `backend/app/services/thread_service.py` | 返回结构化草稿和人工交接状态 |
| Modify | `backend/app/models/ticket_context.py` | 关联草稿、权威工单和交接项 |
| Modify | `frontend/src/views/AssistantView.vue` | 展示可编辑工单草稿和转人工结果 |
| Modify | `frontend/src/views/TicketDetailView.vue` | 显示创建来源和当前责任信息 |
| Modify | `frontend/src/types/index.ts` | 对齐草稿/交接契约 |
| Modify | `frontend/src/api/index.ts` | 草稿修改、确认和转人工调用 |
| Modify | `backend/tests/api/test_http_flow.py` | FAQ 故障和工单确认回归 |

### B4 会话中心与内置请假

实施补充（2026-10-12）：新增 `backend/app/services/leave_attachment_service.py`、`backend/app/providers/file_scanner.py`、`backend/migrations/versions/0007_leave_attachment_storage.py`、`backend/tests/api/test_leave_attachments.py`、`backend/tests/unit/test_file_scanner.py`，修改配置、依赖、测试隔离和 `.env.example`。附件使用本地私有存储、内容解析和可配置 ClamAV 扫描；未扫描、扫描失败或感染不得用于审批或下载。前端补充 Vitest 配置、测试 setup、工作台测试、附件组件及共享样式/日期/角色工具。后续迁移按真实链编号顺延。

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/models/leave_application.py` | 内置请假申请稳定业务实体 |
| Create | `backend/app/models/leave_application_version.py` | 不可覆盖的表单版本与规则快照 |
| Create | `backend/app/models/leave_attachment.py` | 附件元数据和存储引用 |
| Create | `backend/app/providers/builtin.py` | 内置身份、请假、审批、工单和通知 Provider |
| Create | `backend/app/services/task_service.py` | 历史会话/当前任务服务端投影 |
| Create | `backend/app/services/leave_application_service.py` | 草稿、版本、提交、预检和差异 |
| Create | `backend/app/api/routers/tasks.py` | 任务列表、详情、重试和转人工 API |
| Create | `backend/app/api/routers/leaves.py` | 请假草稿、修改、提交、版本和差异 API |
| Create | `backend/app/schemas/task.py` | 统一任务摘要和可用操作 |
| Create | `backend/app/schemas/leave_application.py` | 请假表单、版本和差异契约 |
| Create | `backend/migrations/versions/0005_tasks_and_builtin_leave.py` | 内置请假与任务投影结构 |
| Create | `frontend/src/views/TaskCenterView.vue` | 历史会话和当前任务列表 |
| Create | `frontend/src/views/LeaveListView.vue` | 本人请假列表和状态筛选 |
| Create | `frontend/src/views/LeaveFormView.vue` | 请假草稿、附件元数据和预检修正 |
| Create | `frontend/src/views/ApprovalInboxView.vue` | 当前审批人待办列表 |
| Create | `frontend/src/components/TaskSummary.vue` | 任务状态、责任人和下一步展示 |
| Create | `frontend/src/components/LeaveDiff.vue` | 申请版本字段差异展示 |
| Create | `backend/tests/api/test_task_list.py` | 会话任务隔离和恢复测试 |
| Create | `backend/tests/api/test_builtin_leave_flow.py` | 填单、预检、逐级审批、驳回重提 E2E API |
| Modify | `backend/app/api/routers/threads.py` | 增加历史会话列表并对齐任务投影 |
| Modify | `backend/app/main.py` | 挂载 tasks/leaves 路由 |
| Modify | `frontend/src/router/index.ts` | 注册任务、请假、审批工作台路由 |
| Modify | `frontend/src/App.vue` | 按角色展示导航并从服务端恢复入口 |
| Modify | `frontend/src/stores/assistant.ts` | localStorage 仅保存界面偏好 |
| Modify | `frontend/src/api/index.ts` | 增加任务和内置请假 API |
| Modify | `frontend/src/types/index.ts` | 增加任务和请假领域类型 |

### B5 客服运营闭环

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/models/ticket_record.py` | 内置权威工单和外部投影 |
| Create | `backend/app/models/ticket_feedback.py` | 用户反馈与复盘关联 |
| Create | `backend/app/models/ticket_assignment_rule.py` | 版本化队列分派规则 |
| Create | `backend/app/services/support_queue_service.py` | 人工队列受理、转派和完成 |
| Create | `backend/app/services/ticket_service.py` | 创建、重复候选、合并、分派和反馈 |
| Create | `backend/app/api/routers/support.py` | 客服队列和处理回写 API |
| Create | `backend/app/schemas/support.py` | 队列、合并、分派和反馈契约 |
| Create | `backend/migrations/versions/0006_support_ticket_operations.py` | 权威工单、反馈和分派规则结构 |
| Create | `frontend/src/views/SupportQueueView.vue` | 人工队列筛选、受理和转派 |
| Create | `frontend/src/views/SupportWorkItemView.vue` | 交接上下文和处理回写 |
| Create | `frontend/src/views/TicketWorkbenchView.vue` | 客服工单合并、分派和进度维护 |
| Create | `frontend/src/components/TicketFeedback.vue` | 已解决/仍需帮助反馈 |
| Create | `backend/tests/api/test_support_queue.py` | 队列授权、受理并发和回写测试 |
| Create | `backend/tests/api/test_ticket_operations.py` | 合并、分派和负反馈复盘测试 |
| Modify | `backend/app/api/routers/tickets.py` | 正式工单操作与反馈入口 |
| Modify | `backend/app/providers/builtin.py` | 内置工单 Provider 实现 |
| Modify | `frontend/src/views/TicketDetailView.vue` | 处理进度与反馈交互 |
| Modify | `frontend/src/router/index.ts` | 注册客服队列和工作台路由 |
| Modify | `frontend/src/App.vue` | 客服角色菜单 |
| Modify | `frontend/src/api/index.ts` | 客服与正式工单 API |
| Modify | `frontend/src/types/index.ts` | 客服、工单、反馈类型 |

### B6 知识与策略治理

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/models/knowledge_source.py` | 稳定知识来源与默认责任人 |
| Create | `backend/app/models/knowledge_version.py` | 文件版本、发布状态、权限和生失效期 |
| Create | `backend/app/models/knowledge_file.py` | 原文件元数据和对象存储引用 |
| Create | `backend/app/models/policy_version.py` | 不可变策略版本和发布/回滚关系 |
| Create | `backend/app/storage/base.py` | ObjectStore 协议 |
| Create | `backend/app/storage/local.py` | 开发环境受限本地对象存储 |
| Create | `backend/app/services/document_parser.py` | Markdown/HTML/PDF 解析与来源定位 |
| Create | `backend/app/services/knowledge_version_service.py` | 上传、预览、发布、失效和检索版本解析 |
| Create | `backend/app/services/policy_version_service.py` | 策略校验、发布、匹配和回滚 |
| Create | `backend/app/schemas/knowledge_version.py` | 文件上传、预览和版本契约 |
| Create | `backend/app/schemas/policy_version.py` | 策略草稿、发布和回滚契约 |
| Create | `backend/migrations/versions/0007_knowledge_and_policy_versions.py` | 知识/策略版本模型及旧数据回填 |
| Create | `frontend/src/views/KnowledgeSourceView.vue` | 来源、版本、预览与发布页面 |
| Create | `frontend/src/views/PolicyVersionView.vue` | 灰度策略版本、发布和回滚页面 |
| Create | `backend/tests/unit/test_document_parser.py` | 三种格式解析与定位测试 |
| Create | `backend/tests/api/test_knowledge_versions.py` | 权限、生失效和版本检索测试 |
| Create | `backend/tests/api/test_policy_versions.py` | 优先级、校验、发布和回滚测试 |
| Modify | `backend/app/models/knowledge_chunk.py` | 切片关联具体版本与页/段定位 |
| Modify | `backend/app/services/knowledge_service.py` | 只检索当前有效且授权版本 |
| Modify | `backend/app/services/policy_service.py` | 转调不可变版本匹配服务 |
| Modify | `backend/app/api/routers/knowledge.py` | 文件上传、预览和版本生命周期 API |
| Modify | `backend/app/api/routers/policies.py` | 草稿、发布和回滚 API |
| Modify | `frontend/src/views/KnowledgeView.vue` | 导航到来源治理并保留旧入口兼容 |
| Modify | `frontend/src/views/ConfigView.vue` | 导航到策略版本并保留旧入口兼容 |
| Modify | `backend/requirements.txt` | 增加受控 PDF/HTML 解析依赖 |

### B7 审计、观测与降级

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/models/audit_export.py` | 受控导出任务、筛选哈希和文件过期 |
| Create | `backend/app/models/model_usage.py` | 模型请求和 token 是否已知 |
| Create | `backend/app/services/runtime_trace_service.py` | Span 记录、聚合和 trace 下钻 |
| Create | `backend/app/services/audit_export_service.py` | 权限化、脱敏化审计导出 |
| Create | `backend/app/services/degradation_service.py` | 场景降级、在途策略和恢复控制 |
| Create | `backend/app/api/routers/operations.py` | 指标、trace、健康和降级 API |
| Create | `backend/app/schemas/operations.py` | 指标、Span、降级和导出契约 |
| Create | `backend/migrations/versions/0008_observability_and_exports.py` | 模型用量和导出结构 |
| Create | `frontend/src/views/OperationsView.vue` | 运行指标与 trace 下钻 |
| Create | `frontend/src/views/DegradationView.vue` | 场景降级和恢复控制 |
| Create | `frontend/src/components/RuntimeTrace.vue` | 节点、工具和错误时间线 |
| Create | `backend/tests/api/test_audit_export.py` | 导出授权、脱敏和导出审计测试 |
| Create | `backend/tests/api/test_operations.py` | 指标聚合、缺失 token 和 trace 测试 |
| Create | `backend/tests/api/test_degradation.py` | 新任务回退与在途任务策略测试 |
| Modify | `backend/app/services/audit_service.py` | 规范业务审计主体、资源和结果字段 |
| Modify | `backend/app/api/routers/audit.py` | trace 筛选、导出创建和状态查询 |
| Modify | `backend/app/llm/ark_llm.py` | 记录模型耗时和 token 统计 |
| Modify | `backend/app/graph/graph_service.py` | 节点 Span 和恢复 trace 关联 |
| Modify | `frontend/src/views/AuditView.vue` | 组合筛选、受控导出和 trace 跳转 |
| Modify | `frontend/src/router/index.ts` | 注册运维和降级页面 |
| Modify | `frontend/src/App.vue` | 审计/运维角色菜单 |

### B8 真实 OA 与上线验证

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | `backend/app/providers/real.py` | 配置化真实 OA HTTP Provider |
| Create | `backend/app/providers/http_client.py` | 认证、超时、有限重试和关联编号 |
| Create | `backend/app/api/routers/readiness.py` | 能力探测、存活和就绪详情 |
| Create | `backend/tests/contract/test_provider_contract.py` | 三种 Provider 共用契约套件 |
| Create | `backend/tests/contract/test_real_provider_http.py` | HTTP 错误映射、幂等和超时测试 |
| Create | `backend/tests/security/test_access_boundaries.py` | 跨租户、资源越权和撤权测试 |
| Create | `backend/tests/security/test_prompt_injection.py` | 用户/知识提示注入隔离测试 |
| Create | `backend/tests/recovery/test_crash_recovery.py` | 写入后崩溃对账恢复测试 |
| Create | `backend/tests/performance/test_p1_baseline.py` | FAQ 与预检初始性能基线 |
| Create | `frontend/e2e/p1-formalization.spec.ts` | 五类角色关键流程 E2E |
| Create | `frontend/playwright.config.ts` | 隔离 E2E 环境配置 |
| Create | `docs/production-deployment.md` | 正式配置、迁移、探针和发布步骤 |
| Create | `docs/p1-acceptance-report.md` | F-001～F-044 验收证据索引 |
| Modify | `backend/app/adapters/real_adapter.py` | 兼容 facade 转调 Real Provider |
| Modify | `backend/app/core/config.py` | 真实 OA 地址、认证和重试配置 |
| Modify | `backend/app/main.py` | 挂载 readiness 并执行生产配置校验 |
| Modify | `docker-compose.yml` | 增加后端、前端、迁移与健康检查服务 |
| Modify | `README.md` | 双模式启动、迁移和验证入口 |
| Modify | `docs/rollback-runbook.md` | 数据、应用、Provider 和降级回滚步骤 |
| Modify | `docs/manual-verification.md` | 最终页面化 P1 全量手动验收 |
| Modify | `frontend/package.json` | 增加组件测试和 Playwright 命令 |

## Interfaces

### Cross-Batch Types

```text
ProviderCapabilities {
  identity: bool; leave_read: bool; approval_write: bool;
  ticket_write: bool; notification: bool
}

CommandEnvelope[T] {
  command_id: UUID; idempotency_key: string; actor_id: string;
  tenant_id: string; resource_type: string; resource_id?: string;
  payload: T; payload_hash: string; trace_id: string; policy_version?: string
}

TaskSummary {
  id: UUID; thread_id: UUID; scene: string; title: string; status: string;
  next_action: string; responsibility: Responsibility;
  business_id?: string; available_actions: string[]; updated_at: datetime
}

AuthorizationDecision {
  allowed: bool; reason_code: string; resource_scope: object;
  tool_allowlist: string[]; evaluated_at: datetime
}
```

### Batch Contracts

| Batch | Produces | Consumed By |
| --- | --- | --- |
| B1 | ProviderBundle、CommandEnvelope、AuthorizationDecision、迁移/测试安全基线 | B2～B8 全部业务写入和测试 |
| B2 | ApprovalInstance、ApprovalNode、ApprovalDecision、节点状态机 | B4 内置请假、B7 观测、B8 Provider 契约 |
| B3 | HumanQueueItem、HandoffSnapshot、TicketDraft | B5 客服运营、B7 转人工指标 |
| B4 | TaskSummary、LeaveApplication/Version、builtin Provider | B5 页面导航、B7 任务下钻、B8 双模式验收 |
| B5 | TicketRecord、TicketFeedback、AssignmentRule | B7 指标与审计、B8 工单 Provider 契约 |
| B6 | KnowledgeSource/Version、PolicyVersion、ObjectStore | B7 策略/知识审计、B8 安全验收 |
| B7 | RuntimeSpan、ModelUsage、AuditExport、DegradationState | B8 上线门槛与验收报告 |
| B8 | real Provider、readiness、部署与完整验收证据 | 正式发布 |

## Batch 1：正式化底座

**Depends on:** 无。提案、规格、设计和执行契约已批准后方可开始。

### Task 1.1：建立 Alembic 基线和非破坏升级

**Requirements:** P1-PLAT-003

**Files:** `backend/alembic.ini`、`backend/migrations/env.py`、`backend/migrations/script.py.mako`、`backend/migrations/versions/0001_mvp_baseline.py`、`backend/migrations/versions/0002_command_and_runtime_foundation.py`、`backend/tests/migrations/test_mvp_upgrade.py`、`backend/app/main.py`

**Interfaces:** Produces schema revisions `0001`/`0002`; consumed by every later migration. Consumes current `Base.metadata` only for comparison, not runtime table creation.

1. **Red:** 添加包含现有样本数据的升级测试，并断言升级后行数、主键和状态不变。
2. **Red Verify:** 对无迁移目录的当前代码运行测试，确认因 Alembic revision 缺失失败。
3. **Green:** 创建基线和扩张迁移，将生产启动改为检查 revision 而非 `create_all`。
4. **Green Verify:** 在空测试库和 MVP 样本测试库分别执行 `upgrade head` 两次并通过断言。
5. **Refactor:** 提取测试迁移助手，运行现有单元测试确认 ORM 初始化未回归。

### Task 1.2：隔离测试数据库

**Requirements:** P1-PLAT-004

**Files:** `backend/tests/conftest.py`、`backend/app/core/config.py`、`backend/.env.example`

**Interfaces:** Produces validated `test_database_url`; consumed by all API、迁移、恢复和性能测试。

1. **Red:** 添加三项拒绝测试：非 test 环境、库名无 `_test`、未设置清理许可。
2. **Red Verify:** 指向开发数据库运行夹具初始化，确认测试在执行 SQL 前失败。
3. **Green:** 实现环境、库名和显式清理标志三重校验，并创建独立测试会话。
4. **Green Verify:** 使用测试库运行一个 API 测试，确认清理后开发库行数未变化。
5. **Refactor:** 集中测试 URL 解析与错误消息，运行 `tests/unit` 和安全闸门测试。

### Task 1.3：统一命令幂等和错误契约

**Requirements:** P1-PLAT-005、P1-PLAT-007

**Files:** `backend/app/models/idempotency_record.py`、`backend/app/schemas/command.py`、`backend/app/services/idempotency_service.py`、`backend/app/core/errors.py`、`backend/app/core/enums.py`、`backend/app/models/__init__.py`、`backend/tests/unit/test_idempotency_service.py`

**Interfaces:** Produces `CommandEnvelope[T]` and idempotency begin/complete/fail API; consumed by B2 approval, B3 handoff/ticket, B5 feedback, B7 export and B8 real writes.

1. **Red:** 测试同键同载荷复用、同键异载荷冲突、`UNKNOWN` 对账和并发占用。
2. **Red Verify:** 运行新测试，确认因模型与服务不存在失败。
3. **Green:** 实现载荷规范化哈希、作用域唯一键和事务内状态转换。
4. **Green Verify:** 运行幂等测试和当前重复会话/消息 API 测试。
5. **Refactor:** 将统一错误码接入 `ApiResponse`，运行后端单元测试全集。

### Task 1.4：ProviderBundle 与实时资源授权

**Requirements:** F-011、F-013、P1-PLAT-001、P1-PLAT-006

**Files:** `backend/app/providers/base.py`、`backend/app/providers/bundle.py`、`backend/app/services/authorization_service.py`、`backend/app/adapters/oa_adapter.py`、`backend/app/adapters/factory.py`、`backend/app/middleware/auth.py`、`backend/app/core/config.py`、`backend/tests/unit/test_authorization_service.py`、`backend/tests/unit/test_provider_bundle.py`

**Interfaces:** Produces `ProviderCapabilities` and `AuthorizationDecision`; consumes authenticated user context and active policy; B2～B8 must call authorization before resource read/write.

1. **Red:** 测试生产 Mock 认证拒绝、能力缺失、跨租户资源和动态工具拒绝。
2. **Red Verify:** 运行测试，确认当前 factory 与 Mock 中间件无法满足断言。
3. **Green:** 实现能力协议、Bundle 选择、兼容 facade 和集中授权服务。
4. **Green Verify:** 运行新增测试及现有权限/工具白名单测试。
5. **Refactor:** 移除路由中可由授权服务替代的重复角色判断，并执行静态导入检查。

**Batch 1 Exit:** 迁移、测试安全闸门、幂等和授权测试通过；现有前端构建成功；更新手动验证文档。进入 B2 前向用户报告结果与影响。

## Batch 2：现有请假流纠正

**Depends on:** Batch 1 通过。

### Task 2.1：建立审批实例与有序节点状态机

**Requirements:** F-022、F-023、F-024

**Files:** `backend/app/models/approval_instance.py`、`backend/app/models/approval_node.py`、`backend/app/models/approval_decision.py`、`backend/app/services/approval_service.py`、`backend/app/schemas/approval_v2.py`、`backend/migrations/versions/0003_approval_instances.py`、`backend/tests/unit/test_approval_state_machine.py`

**Interfaces:** Consumes B1 `CommandEnvelope`/authorization; produces node-level `ApprovalDetail` and decisions for B4 UI and B7 trace.

1. **Red:** 添加两级批准、越级拒绝、驳回、重复决定和编辑字段校验测试。
2. **Red Verify:** 运行状态机测试，确认当前单决定模型错误地结束全流程。
3. **Green:** 实现实例、节点、决定模型及事务内逐级推进服务。
4. **Green Verify:** 运行状态机测试并验证一个实例最多一个活动节点。
5. **Refactor:** 提取合法迁移表和决定校验器，运行迁移升级测试。

### Task 2.2：旧 Interrupt API 接入节点决定

**Requirements:** F-023、F-025、P1-PLAT-005

**Files:** `backend/app/api/routers/interrupts.py`、`backend/app/services/interrupt_service.py`、`backend/app/schemas/interrupt.py`、`backend/app/models/human_decision.py`、`backend/app/repositories/thread_repo.py`、`backend/tests/api/test_approval_permissions.py`、`backend/tests/api/test_http_flow.py`

**Interfaces:** Consumes ApprovalService; old `POST /interrupts/{id}/resume` produces the same formal decision as the new node command.

1. **Red:** 添加当前/非当前审批人、同键异载荷、并发提交和旧接口兼容测试。
2. **Red Verify:** 运行测试，确认非当前链路成员仍能结束当前流程。
3. **Green:** 将旧接口转调 ApprovalService，并统一幂等和状态冲突响应。
4. **Green Verify:** 运行审批权限测试及现有 HTTP 全流程测试。
5. **Refactor:** 删除直接写最终状态的重复路径，运行图测试验证中断恢复。

### Task 2.3：节点级催办、升级和安全恢复

**Requirements:** F-025、F-026、P1-PLAT-007

**Files:** `backend/app/services/scheduler.py`、`backend/app/graph/nodes/leave_nodes.py`、`backend/app/services/approval_service.py`、`backend/tests/graph/test_leave_flow.py`、`backend/tests/unit/test_approval_state_machine.py`

**Interfaces:** Consumes active ApprovalNode and CommandEnvelope; produces idempotent nudge/escalation audit events and resumable paused state.

1. **Red:** 添加节点催办一次、升级一次、调度重启、依赖故障暂停和恢复测试。
2. **Red Verify:** 运行测试，确认当前线程级时间戳无法区分审批节点。
3. **Green:** 将调度器改为扫描活动节点，并让图写入前对账权威审批状态。
4. **Green Verify:** 运行调度、图和幂等相关测试。
5. **Refactor:** 集中时间阈值与通知命令生成，运行后端安全测试子集。

### Task 2.4：修正现有审批界面

**Requirements:** F-002、F-023、F-026

**Files:** `frontend/src/components/ApprovalCard.vue`、`frontend/src/views/LeaveDetailView.vue`、`frontend/src/types/index.ts`、`frontend/src/api/index.ts`

**Interfaces:** Consumes `ApprovalDetail` and structured edit decision; produces idempotent node decision command.

1. **Red:** 添加前端组件测试断言非当前节点无按钮、编辑决定要求字段和暂停状态有入口。
2. **Red Verify:** 运行组件测试，确认当前卡片始终显示三种按钮且编辑无数据。
3. **Green:** 实现活动节点、历史决定、结构化编辑和错误/重试展示。
4. **Green Verify:** 运行组件测试、TypeScript 检查和生产构建。
5. **Refactor:** 提取状态映射和决定表单子组件，手动验证员工/两级审批人视图。

**Batch 2 Exit:** 严格逐级审批、越级保护、幂等决定、节点催办和暂停恢复通过；旧流程链接仍可读取。

## Batch 3：现有 FAQ/工单纠正

**Depends on:** Batch 2 通过。

### Task 3.1：将转人工落为正式队列项和快照

**Requirements:** F-003、F-031

**Files:** `backend/app/models/human_queue_item.py`、`backend/app/models/handoff_snapshot.py`、`backend/app/services/handoff_service.py`、`backend/app/schemas/handoff.py`、`backend/migrations/versions/0004_handoff_and_ticket_draft.py`、`backend/app/graph/nodes/faq_nodes.py`、`backend/tests/unit/test_handoff_service.py`

**Interfaces:** Consumes Task/thread context and authorization; produces `HumanQueueItemSummary` and immutable `HandoffSnapshot` for B5.

1. **Red:** 测试主动转人工、FAQ 未命中、检索故障、重复触发和敏感字段脱敏。
2. **Red Verify:** 运行测试，确认当前仅返回 `next_action=human` 而无队列记录。
3. **Green:** 实现队列/快照模型、幂等交接服务并接入 FAQ 节点。
4. **Green Verify:** 运行交接测试和知识检索单元测试。
5. **Refactor:** 集中交接摘要白名单，运行授权测试防止未授权读取。

### Task 3.2：可编辑工单草稿后再确认创建

**Requirements:** F-032、F-034

**Files:** `backend/app/models/ticket_draft.py`、`backend/app/services/ticket_draft_service.py`、`backend/app/schemas/ticket_draft.py`、`backend/app/graph/nodes/ticket_nodes.py`、`backend/app/api/routers/tickets.py`、`backend/app/models/ticket_context.py`、`backend/tests/api/test_ticket_draft_flow.py`

**Interfaces:** Consumes extracted ticket fields; produces versioned editable draft and confirmation CommandEnvelope for B5 TicketService.

1. **Red:** 测试草稿字段修改、非法优先级、未确认不写工单、刷新恢复和重复确认。
2. **Red Verify:** 运行测试，确认当前抽取结果不可编辑且确认契约不完整。
3. **Green:** 实现草稿模型、修改/确认服务并让图只在确认后调用写工具。
4. **Green Verify:** 运行草稿 API、图和当前工单回归测试。
5. **Refactor:** 统一字段字典与校验，运行迁移升级测试。

### Task 3.3：修正 FAQ/工单前端交互

**Requirements:** F-002、F-003、F-032、F-034

**Files:** `frontend/src/views/AssistantView.vue`、`frontend/src/views/TicketDetailView.vue`、`frontend/src/types/index.ts`、`frontend/src/api/index.ts`、`backend/app/services/thread_service.py`、`backend/tests/api/test_http_flow.py`

**Interfaces:** Consumes TicketDraft and handoff summaries; produces validated draft patch/confirm commands.

1. **Red:** 添加前端测试断言草稿字段可修改、人工交接号可见和未确认不显示正式工单号。
2. **Red Verify:** 运行测试，确认现有助手只显示抽取结果或直接确认。
3. **Green:** 接入草稿编辑、确认和人工交接状态，详情返回结构化责任信息。
4. **Green Verify:** 运行前端测试、构建和后端 HTTP 回归。
5. **Refactor:** 拆分草稿表单组件并更新 B3 手动验证步骤。

**Batch 3 Exit:** FAQ 故障不猜测且生成交接记录；工单确认前可修改；已有功能正式化阶段完成。

## Batch 4：会话中心与内置请假（新增功能，开工前必须报备确认）

**Depends on:** Batch 3 通过且用户明确批准 B4。

### Task 4.1：服务端历史会话与统一任务投影

**Requirements:** F-001、F-002、F-004

**Files:** `backend/app/services/task_service.py`、`backend/app/api/routers/tasks.py`、`backend/app/schemas/task.py`、`backend/app/api/routers/threads.py`、`backend/app/main.py`、`backend/tests/api/test_task_list.py`

**Interfaces:** Consumes AgentThread/approval/handoff projections; produces paginated `TaskSummary` and task actions.

1. **Red:** 测试本人列表、审批人列表、跨租户隔离、分页筛选和暂停动作。
2. **Red Verify:** 运行测试，确认当前没有列表接口。
3. **Green:** 实现任务投影服务、列表/详情/重试/交接路由。
4. **Green Verify:** 运行任务 API 和授权测试。
5. **Refactor:** 优化查询索引与投影构造，检查分页 SQL 次数。

### Task 4.2：内置请假草稿、版本和附件元数据

**Requirements:** F-020、F-021、F-024、P1-PLAT-001

**Files:** `backend/app/models/leave_application.py`、`backend/app/models/leave_application_version.py`、`backend/app/models/leave_attachment.py`、`backend/app/providers/builtin.py`、`backend/app/services/leave_application_service.py`、`backend/app/schemas/leave_application.py`、`backend/app/api/routers/leaves.py`、`backend/migrations/versions/0005_tasks_and_builtin_leave.py`、`backend/tests/api/test_builtin_leave_flow.py`

**Interfaces:** Produces LeaveApplication/Version and form diff; consumes ApprovalService and precheck tools through builtin Provider.

1. **Red:** 测试草稿保存、所有权、完整预检、附件规则、版本差异和驳回重提。
2. **Red Verify:** 运行测试，确认系统只能引用 Mock 业务号。
3. **Green:** 实现内置申请模型、Provider、领域服务及 API。
4. **Green Verify:** 运行内置请假全流程、迁移和预检单元测试。
5. **Refactor:** 提取表单快照规范化与差异算法，验证旧 Mock 流程兼容。

### Task 4.3：任务、请假和审批工作台页面

验收补充（2026-10-12）：新增 `backend/tests/e2e/b4_browser.py`，使用已有 Edge 与 Playwright 对真实前后端执行页面验收；运行依赖及截图仅保存于忽略的 `data/verification/`。验收服务只能连接独立测试库，审批详情补齐附件元数据、扫描状态、受控下载及加载重试。未配置 ClamAV 的真实页面验收不得将附件判为 CLEAN；扫描通过下载由独立自动化测试验证并明确记录浏览器限制。

**Requirements:** F-001、F-002、F-020～F-024

**Files:** `frontend/src/views/TaskCenterView.vue`、`frontend/src/views/LeaveListView.vue`、`frontend/src/views/LeaveFormView.vue`、`frontend/src/views/ApprovalInboxView.vue`、`frontend/src/components/TaskSummary.vue`、`frontend/src/components/LeaveDiff.vue`、`frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/stores/assistant.ts`、`frontend/src/api/index.ts`、`frontend/src/types/index.ts`

**Interfaces:** Consumes TaskSummary, LeaveApplication/Version and ApprovalDetail; produces form patch/submit and node decision commands.

实施补充文件（2026-10-12）：`frontend/package.json`、`frontend/package-lock.json`、`frontend/vitest.config.ts`、`frontend/src/tests/b4-workbench.test.ts`、`frontend/src/tests/setup.ts`、`frontend/src/api/client.ts`、`frontend/src/utils/roles.ts`、`frontend/src/utils/leave.ts`、`frontend/src/views/AssistantView.vue`、`frontend/src/views/LeaveDetailView.vue`、`frontend/src/views/ConfigView.vue`、`frontend/src/components/ApprovalCard.vue`、`frontend/src/components/PrecheckTable.vue`、`frontend/src/utils/status.ts`、`frontend/src/main.ts`、`frontend/src/styles/workbench.css`。审批待办的计数与分页必须在后端筛选，补充 `backend/app/services/task_service.py`、`backend/app/api/routers/tasks.py`、`backend/tests/api/test_task_list.py`。

1. **Red:** 添加员工填单/重提、审批待办、服务端恢复和菜单切换组件测试。
2. **Red Verify:** 运行测试，确认当前没有表单、列表或待办页。
3. **Green:** 实现四个页面、两个组件、角色菜单和服务端恢复。
4. **Green Verify:** 运行组件测试、TypeScript 构建和 B4 API E2E。
5. **Refactor:** 统一空/加载/暂停/无权状态，更新完整请假手工验证。

**Batch 4 Exit:** 用户无需 Mock 业务号即可在页面完成请假创建、修改、预检、逐级审批和驳回重提。

## Batch 5：客服运营闭环（新增功能，开工前必须报备确认）

**Depends on:** Batch 4 通过且用户明确批准 B5。

### Task 5.1：内置权威工单、重复候选和分派规则

**Requirements:** F-033

**Files:** `backend/app/models/ticket_record.py`、`backend/app/models/ticket_assignment_rule.py`、`backend/app/services/ticket_service.py`、`backend/app/schemas/support.py`、`backend/migrations/versions/0006_support_ticket_operations.py`、`backend/app/providers/builtin.py`、`backend/app/api/routers/tickets.py`、`backend/tests/api/test_ticket_operations.py`

**Interfaces:** Consumes confirmed TicketDraft; produces TicketRecord, duplicate candidates and assignment result.

1. **Red:** 测试创建、重复候选、确认合并、规则分派、分派失败和越权查询。
2. **Red Verify:** 运行测试，确认当前适配器合并/分派语义不可验证。
3. **Green:** 实现权威工单、规则、服务和内置 Provider。
4. **Green Verify:** 运行工单操作、授权和幂等测试。
5. **Refactor:** 将重复评分和规则匹配改为可测试纯函数，验证查询索引。

### Task 5.2：人工队列受理和处理回写

**Requirements:** F-003、F-031、F-033

**Files:** `backend/app/services/support_queue_service.py`、`backend/app/api/routers/support.py`、`backend/app/schemas/support.py`、`backend/app/main.py`、`backend/tests/api/test_support_queue.py`

**Interfaces:** Consumes HumanQueueItem/HandoffSnapshot; produces assignment, resolution and linked TicketRecord updates.

1. **Red:** 测试客服队列范围、并发受理、转派、完成和非客服拒绝。
2. **Red Verify:** 运行测试，确认当前无客服队列 API。
3. **Green:** 实现受理事务、SLA 状态、转派和结果回写接口。
4. **Green Verify:** 运行客服队列与授权测试。
5. **Refactor:** 统一队列筛选和责任人投影，检查并发受理只成功一次。

### Task 5.3：用户反馈和复盘闭环

**Requirements:** F-035

**Files:** `backend/app/models/ticket_feedback.py`、`backend/app/services/ticket_service.py`、`backend/app/api/routers/tickets.py`、`backend/tests/api/test_ticket_operations.py`、`frontend/src/components/TicketFeedback.vue`、`frontend/src/views/TicketDetailView.vue`

**Interfaces:** Consumes resolved TicketRecord; produces idempotent feedback and negative-review HumanQueueItem.

1. **Red:** 测试已解决/仍需帮助、重复反馈、重开和复盘项创建。
2. **Red Verify:** 运行测试，确认预留 feedback 字段没有 API 行为。
3. **Green:** 实现反馈实体、命令和负反馈复盘逻辑，并接前端控件。
4. **Green Verify:** 运行反馈 API、组件测试和构建。
5. **Refactor:** 统一反馈状态文本和审计摘要，更新用户验收步骤。

### Task 5.4：客服队列与工单工作台

**Requirements:** F-003、F-033、F-035

**Files:** `frontend/src/views/SupportQueueView.vue`、`frontend/src/views/SupportWorkItemView.vue`、`frontend/src/views/TicketWorkbenchView.vue`、`frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/api/index.ts`、`frontend/src/types/index.ts`

**Interfaces:** Consumes support queue, handoff snapshot and ticket operation APIs; produces accept/assign/merge/resolve commands.

1. **Red:** 添加客服角色菜单、队列受理、上下文展示和合并确认测试。
2. **Red Verify:** 运行测试，确认当前没有客服操作页面。
3. **Green:** 实现三个工作台页面和角色路由。
4. **Green Verify:** 运行前端测试、构建及客服 E2E。
5. **Refactor:** 提取队列筛选与工单操作组件，执行无权限页面手工验证。

**Batch 5 Exit:** FAQ/工单可转入真实人工队列，客服可受理/分派/合并/回写，用户负反馈可复盘。

## Batch 6：知识与策略治理（新增功能，开工前必须报备确认）

**Depends on:** Batch 5 通过且用户明确批准 B6。

### Task 6.1：文件存储和三格式解析

**Requirements:** F-030、F-041

**Files:** `backend/app/storage/base.py`、`backend/app/storage/local.py`、`backend/app/services/document_parser.py`、`backend/app/schemas/knowledge_version.py`、`backend/requirements.txt`、`backend/tests/unit/test_document_parser.py`

**Interfaces:** Produces parsed blocks `{text,page,section,paragraph}` and file reference; consumed by KnowledgeVersionService.

1. **Red:** 测试 Markdown 标题、HTML 正文、PDF 页码、空文件和非法类型。
2. **Red Verify:** 运行测试，确认当前仅接受文本内容。
3. **Green:** 实现受限 ObjectStore 和三格式解析器。
4. **Green Verify:** 运行解析、路径安全和现有分块测试。
5. **Refactor:** 统一解析块结构与错误码，检查文件句柄释放。

### Task 6.2：知识来源、版本和发布生命周期

**Requirements:** F-030、F-041

**Files:** `backend/app/models/knowledge_source.py`、`backend/app/models/knowledge_version.py`、`backend/app/models/knowledge_file.py`、`backend/app/models/knowledge_chunk.py`、`backend/app/services/knowledge_version_service.py`、`backend/app/services/knowledge_service.py`、`backend/app/api/routers/knowledge.py`、`backend/migrations/versions/0007_knowledge_and_policy_versions.py`、`backend/tests/api/test_knowledge_versions.py`

**Interfaces:** Consumes parsed blocks; produces current published KnowledgeVersion and permission-filtered citations.

1. **Red:** 测试新版本、单一当前发布版、生失效、权限过滤、解析失败和旧数据回填。
2. **Red Verify:** 运行测试，确认当前文档记录无法表达稳定来源和历史版本。
3. **Green:** 实现四层模型、发布服务、迁移和检索改造。
4. **Green Verify:** 运行知识 API、检索、迁移和权限测试。
5. **Refactor:** 优化当前版本查询并验证引用能定位页/段。

### Task 6.3：不可变策略版本、灰度和回滚

**Requirements:** F-040、F-044

**Files:** `backend/app/models/policy_version.py`、`backend/app/services/policy_version_service.py`、`backend/app/services/policy_service.py`、`backend/app/schemas/policy_version.py`、`backend/app/api/routers/policies.py`、`backend/tests/api/test_policy_versions.py`

**Interfaces:** Produces resolved PolicySnapshot by user/dept/tenant/global precedence; consumed by routing, tool authorization, scheduler and degradation.

1. **Red:** 测试作用域优先级、阈值校验、发布不可变、回滚新版本和在途快照。
2. **Red Verify:** 运行测试，确认当前 upsert 覆盖历史配置。
3. **Green:** 实现版本服务、解析优先级、发布/回滚 API。
4. **Green Verify:** 运行策略、授权和调度测试。
5. **Refactor:** 集中场景 schema 校验并记录策略命中解释。

### Task 6.4：知识和策略治理页面

**Requirements:** F-040、F-041

**Files:** `frontend/src/views/KnowledgeSourceView.vue`、`frontend/src/views/PolicyVersionView.vue`、`frontend/src/views/KnowledgeView.vue`、`frontend/src/views/ConfigView.vue`、`frontend/src/api/index.ts`、`frontend/src/types/index.ts`

**Interfaces:** Consumes upload/preview/publish and policy version APIs; produces explicit publish/rollback commands.

1. **Red:** 添加文件预览、版本历史、生失效、策略发布和回滚组件测试。
2. **Red Verify:** 运行测试，确认当前只能粘贴文本并覆盖策略。
3. **Green:** 实现治理页面并保留旧入口跳转。
4. **Green Verify:** 运行前端测试、构建和知识/策略 E2E。
5. **Refactor:** 统一版本时间线和权限标签编辑，更新管理员验收步骤。

**Batch 6 Exit:** Markdown/HTML/PDF 可预览发布，回答可定位具体版本；策略灰度与回滚可追溯。

## Batch 7：审计、观测与降级（新增功能，开工前必须报备确认）

**Depends on:** Batch 6 通过且用户明确批准 B7。

### Task 7.1：业务审计规范化和受控导出

**Requirements:** F-012、F-042

**Files:** `backend/app/models/audit_export.py`、`backend/app/services/audit_service.py`、`backend/app/services/audit_export_service.py`、`backend/app/api/routers/audit.py`、`backend/app/schemas/operations.py`、`backend/migrations/versions/0008_observability_and_exports.py`、`backend/tests/api/test_audit_export.py`

**Interfaces:** Consumes normalized audit filters and AuthorizationDecision; produces expiring export reference and export audit event.

1. **Red:** 测试组合筛选、脱敏、查询/导出权限差异、导出审计和文件过期。
2. **Red Verify:** 运行测试，确认当前只有页面查询而无受控导出。
3. **Green:** 实现规范字段、导出任务和权限化下载引用。
4. **Green Verify:** 运行审计 API、授权和文件访问测试。
5. **Refactor:** 统一动作字典与脱敏策略，验证大分页使用稳定游标。

### Task 7.2：运行 Span、模型用量和 trace 下钻

**Requirements:** F-043

**Files:** `backend/app/models/runtime_span.py`、`backend/app/models/model_usage.py`、`backend/app/services/runtime_trace_service.py`、`backend/app/api/routers/operations.py`、`backend/app/llm/ark_llm.py`、`backend/app/graph/graph_service.py`、`backend/tests/api/test_operations.py`

**Interfaces:** Produces RuntimeSpan/ModelUsage metrics; consumes trace/run/node/tool/model events.

1. **Red:** 测试节点耗时、工具错误、未知 token、转人工率和 trace 授权下钻。
2. **Red Verify:** 运行测试，确认当前审计数据不足以稳定聚合。
3. **Green:** 实现 Span/usage 记录、聚合和下钻接口。
4. **Green Verify:** 运行观测 API、图和模型 Mock 测试。
5. **Refactor:** 增加保留期清理入口和聚合索引，检查记录失败不影响主业务。

### Task 7.3：场景降级和在途任务策略

**Requirements:** F-026、F-044

**Files:** `backend/app/services/degradation_service.py`、`backend/app/api/routers/operations.py`、`backend/app/schemas/operations.py`、`backend/tests/api/test_degradation.py`

**Interfaces:** Consumes PolicySnapshot/ProviderCapabilities/readiness; produces degradation decision for new and in-flight tasks.

1. **Red:** 测试租户/部门/场景关闭、新请求回退、在途继续/暂停和显式恢复。
2. **Red Verify:** 运行测试，确认当前场景开关没有在途策略和恢复控制。
3. **Green:** 实现降级决策服务和管理员控制 API。
4. **Green Verify:** 运行降级、任务和审批恢复测试。
5. **Refactor:** 集中回退原因和用户提示，验证降级不调用模型工具。

### Task 7.4：审计、运行观测和降级页面

**Requirements:** F-042～F-044

**Files:** `frontend/src/views/AuditView.vue`、`frontend/src/views/OperationsView.vue`、`frontend/src/views/DegradationView.vue`、`frontend/src/components/RuntimeTrace.vue`、`frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/api/index.ts`、`frontend/src/types/index.ts`

**Interfaces:** Consumes audit export, metrics, trace and degradation APIs; produces authorized export and degradation commands.

1. **Red:** 添加审计导出、指标下钻、未知 token 标识和降级确认测试。
2. **Red Verify:** 运行测试，确认当前页面没有导出、观测或降级控制。
3. **Green:** 实现页面、角色菜单和 trace 时间线。
4. **Green Verify:** 运行前端测试、构建和审计/运维 E2E。
5. **Refactor:** 统一时间/筛选组件并更新运维验收步骤。

**Batch 7 Exit:** 审计可受控导出，运行指标可下钻，一键降级对新任务与在途任务行为明确。

## Batch 8：真实 OA 与上线验证（新增功能，开工前必须报备确认）

**Depends on:** Batch 7 通过且用户明确批准 B8；真实 OA 沙箱参数由用户或部署方提供。

### Task 8.1：真实 OA HTTP Provider 与能力探测

**Requirements:** P1-PLAT-001、P1-PLAT-002、P1-PLAT-006

**Files:** `backend/app/providers/http_client.py`、`backend/app/providers/real.py`、`backend/app/adapters/real_adapter.py`、`backend/app/core/config.py`、`backend/app/api/routers/readiness.py`、`backend/app/main.py`、`backend/tests/contract/test_provider_contract.py`、`backend/tests/contract/test_real_provider_http.py`

**Interfaces:** Implements ProviderBundle ports; consumes configured endpoint/auth; produces capabilities, domain DTOs and normalized dependency errors.

1. **Red:** 测试认证头、超时、只读有限重试、写入同键对账、错误映射和能力缺失。
2. **Red Verify:** 运行契约测试，确认当前 RealOAAdapter 全部返回 501。
3. **Green:** 实现 HTTP 客户端、real Provider、兼容 facade 和 readiness 能力探测。
4. **Green Verify:** 对 builtin/mock/real stub 运行同一 Provider 契约套件。
5. **Refactor:** 统一日志脱敏与关联编号，确认生产配置不会输出认证密钥。

### Task 8.2：安全、恢复和性能门槛

**Requirements:** F-011、F-026、P1-PLAT-007、P1-PLAT-008

**Files:** `backend/tests/security/test_access_boundaries.py`、`backend/tests/security/test_prompt_injection.py`、`backend/tests/recovery/test_crash_recovery.py`、`backend/tests/performance/test_p1_baseline.py`

**Interfaces:** Consumes all P1 APIs/Providers; produces machine-readable test reports for release acceptance.

1. **Red:** 固化跨租户、动态撤权、注入、写后崩溃和 P95 阈值场景。
2. **Red Verify:** 在未修正的测试分支确认每类门槛至少能捕获一次预期失败。
3. **Green:** 修复测试暴露的配置、恢复和慢查询问题，不扩大 P1 功能范围。
4. **Green Verify:** 在隔离环境运行安全、恢复和性能套件并保存结果。
5. **Refactor:** 稳定数据工厂和计时方法，重复运行验证结果无偶发失败。

### Task 8.3：前端全角色 E2E 与生产构建

**Requirements:** F-001～F-044、P1-PLAT-008

**Files:** `frontend/e2e/p1-formalization.spec.ts`、`frontend/playwright.config.ts`、`frontend/package.json`

**Interfaces:** Consumes stable P1 API/UI routes; produces employee/approver/support/admin/auditor E2E evidence.

1. **Red:** 编写五类角色从登录上下文到业务完成/审计的关键路径断言。
2. **Red Verify:** 逐条运行测试，确认未启动页面或错误权限会明确失败。
3. **Green:** 补齐稳定选择器、隔离测试数据和 E2E 启停脚本。
4. **Green Verify:** 运行 E2E、组件测试和生产构建。
5. **Refactor:** 消除固定等待并改为状态条件，连续运行两次确认可重复。

### Task 8.4：部署、回滚与 P1 验收归档

**Requirements:** P1-PLAT-003、P1-PLAT-008、P1-PLAT-009

**Files:** `docker-compose.yml`、`README.md`、`docs/production-deployment.md`、`docs/rollback-runbook.md`、`docs/manual-verification.md`、`docs/p1-acceptance-report.md`

**Interfaces:** Consumes migration/test/readiness evidence; produces operator commands and F-001～F-044 acceptance index.

1. **Red:** 按全新环境和 MVP 数据环境演练文档，记录缺失或不可执行步骤。
2. **Red Verify:** 确认未补充前至少有迁移、备份恢复或健康探针步骤无法完成。
3. **Green:** 完成 Compose 服务、部署、迁移、备份、恢复、回滚和页面验收文档。
4. **Green Verify:** 从备份恢复后启动全栈，执行健康检查和 P1 手动抽验。
5. **Refactor:** 将命令与环境变量去重，建立验收报告到测试/截图/日志的索引。

**Batch 8 Exit:** 三种 Provider 契约、安全、恢复、性能、E2E 和手动验收通过；部署与回滚演练成功；P1 方可进入发布归档。

## Requirement Coverage

| Requirement | Tasks |
| --- | --- |
| F-001～F-004 | 3.3、4.1、4.3、5.2 |
| F-010～F-013 | 1.4、3.1、7.1、8.2 |
| F-020～F-026 | 2.1～2.4、4.2～4.3、7.3 |
| F-030～F-035 | 3.1～3.3、5.1～5.4、6.1～6.2 |
| F-040～F-044 | 6.2～6.4、7.1～7.4 |
| P1-PLAT-001～009 | 1.1～1.4、4.2、6.1、7.1～7.3、8.1～8.4 |

## Verification Commands

以下命令须在批次实现后执行；API/迁移测试必须先设置隔离测试数据库配置。

```powershell
cd "C:\Users\j\Desktop\OA AGENT SYSTEM\backend"
python -m pytest tests/unit -q
python -m pytest tests/migrations -q
python -m pytest tests/api -q
python -m pytest tests/graph -q
python -m pytest tests/contract tests/security tests/recovery -q

cd "C:\Users\j\Desktop\OA AGENT SYSTEM\frontend"
npm run test
npm run build
npm run test:e2e
```

性能测试只在专用基线环境运行，结果写入验收报告，不与开发机绝对耗时直接比较。

