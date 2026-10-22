# M3 开发任务与覆盖

日期：2026-10-20。已获批准，B1-B7 的批准本地范围已完成实施和串行验证；真实外部服务、生产上线及 M4/V2 仍不在本阶段完成定义内。状态见 execution-plan.md，依据 [执行契约](execution-contract.md) 执行。

## File Structure

以下路径相对项目根目录。Create 为新文件；Modify 保留现有行为并增量修改。文档内路径不是实施完成证明。

| 操作 | 路径 | 职责 |
| --- | --- | --- |
| Create | backend/migrations/versions/0025_reimbursement_workflow.py | 类型化流程关联、报销及事件追踪增量迁移 |
| Create | backend/app/models/oa_reimbursement.py | 报销、不可变提交版本及附件 |
| Create | backend/app/schemas/oa_reimbursement.py | 金额字符串、分值和生命周期输入输出 |
| Create | backend/app/services/oa_workflow_subject.py | 按 scene 解析有类型的流程业务主体 |
| Create | backend/app/services/oa_reimbursement_service.py | 报销草稿、提交、重提、撤回和归档 |
| Create | backend/app/services/oa_reimbursement_attachment_service.py | 绑定报销的私有发票及完整性校验 |
| Create | backend/app/api/routers/oa_reimbursements.py | 人工报销 API |
| Modify | backend/app/models/oa_workflow.py | 类型化关联和正式事件的版本/追踪字段 |
| Modify | backend/app/schemas/oa_workflow.py | 按 scene 校验字段和金额条件 |
| Modify | backend/app/services/oa_workflow_service.py | 发布、路由及共用推进，保留请假语义 |
| Modify | backend/app/services/oa_approval_service.py | 按主体读取审批对象、席位和结果 |
| Modify | backend/app/services/oa_handoff_service.py | 两类流程的转交和恢复 |
| Modify | backend/app/services/oa_workflow_scheduler.py | 两类流程定时器及只读对账 |
| Modify | backend/app/services/oa_leave_service.py | 适配主体接口，保留日期/额度规则 |
| Modify | backend/app/services/oa_command_service.py | 正式共用命令、追踪及原子事件 |
| Modify | backend/app/services/oa_attachment_service.py | 提取既有文件校验供报销共用，保留请假授权 |
| Modify | backend/app/services/oa_access_service.py | 新增资源与主体权限，不按角色名绕过 |
| Modify | backend/app/api/routers/oa_approvals.py | 返回有类型的审批摘要和详情 |
| Modify | backend/app/api/routers/oa_administration.py | 类型化转交、恢复及对账 |
| Create | backend/migrations/versions/0026_builtin_ticket_bridge.py | 正式工单、确认及结果映射迁移 |
| Create | backend/app/models/oa_ticket.py | 工单、规则和反馈 |
| Create | backend/app/models/oa_bridge.py | 绑定版本的确认及对账记录 |
| Create | backend/app/schemas/oa_ticket.py | 正式工单与版本化命令 |
| Create | backend/app/services/oa_ticket_service.py | 工单创建/合并/领取/办理/反馈 |
| Create | backend/app/services/oa_confirmation_service.py | 确认创建、校验与原子消费 |
| Create | backend/app/api/routers/oa_tickets.py | 人工工单及处理 API |
| Create | backend/app/providers/gateway.py | BridgeContext、异步 OAGateway 和 legacy 包装 |
| Create | backend/app/providers/builtin_gateway.py | 核心及辅助契约到正式服务的映射 |
| Modify | backend/app/providers/base.py | 明确能力与辅助读类型 |
| Modify | backend/app/providers/bundle.py | builtin 实例构建与实际能力 |
| Modify | backend/app/adapters/factory.py | 明确同步调用边界与异步网关获取 |
| Modify | backend/app/adapters/oa_adapter.py | 新增工单结果读和明确的辅助读协议 |
| Modify | backend/app/adapters/mock_adapter.py | 显式 Mock 的新增契约兼容 |
| Modify | backend/app/adapters/real_adapter.py | 工单对账和不支持能力明确拒绝 |
| Modify | backend/app/tools/ticket_tools.py | 正式工具通过异步网关 |
| Modify | backend/app/tools/notify_tools.py | 使用通知受理/对账语义 |
| Create | backend/migrations/versions/0027_notification_delivery.py | 正式通知、任务、尝试和收件配置 |
| Create | backend/app/models/oa_notification.py | 分渠道持久化通知与联系信息 |
| Create | backend/app/schemas/oa_notification.py | 收件箱、渠道状态和人工核对输入输出 |
| Create | backend/app/providers/smtp.py | SMTP 有界投递及受理/未知分类 |
| Create | backend/app/services/oa_notification_service.py | 事件接入、站内信、读取权限和联系配置 |
| Create | backend/app/services/oa_notification_worker.py | 租约领取、重试、未知恢复和当前状态检查 |
| Create | backend/app/api/routers/oa_notifications.py | 收件箱、已读、配置与获授权的核对重试 |
| Modify | backend/app/services/scheduler.py | 接入正式渠道 worker，AI 关闭仍可工作 |
| Modify | backend/app/services/work_task_scheduler.py | 将有效工作任务提醒接入正式通知，保持去重 |
| Modify | backend/app/core/config.py | SMTP 有界配置，凭据不进入响应/日志 |
| Create | backend/migrations/versions/0028_formal_ai_scope.py | 正式知识绑定、策略版本和管理审计 |
| Create | backend/app/models/oa_ai_scope.py | 明确租户/部门的知识绑定、策略及审计 |
| Create | backend/app/services/oa_scope_service.py | 正式来源范围、版本和管理授权 |
| Modify | backend/app/services/knowledge_service.py | 检索前过滤及禁止正式旧数据回退 |
| Modify | backend/app/services/knowledge_version_service.py | 正式发布和引用复核 |
| Modify | backend/app/services/policy_service.py | 正式范围策略及保守默认值 |
| Modify | backend/app/services/policy_version_service.py | 正式策略发布与版本权限 |
| Modify | backend/app/services/audit_service.py | 有归属的正式脱敏审计 |
| Modify | backend/app/services/audit_export_service.py | 导出与明细共用业务权限 |
| Modify | backend/app/services/authorization_service.py | 逐 scene 正式工具授权和最新身份复核 |
| Modify | backend/app/services/organization_service.py | 显式新增资源，不自动扩大角色 |
| Modify | backend/app/api/deps.py | 按已隔离入口开放正式权限 |
| Modify | backend/app/api/routers/readiness.py | 实际依赖就绪与安全能力响应 |
| Modify | backend/app/api/routers/knowledge.py | 正式来源管理边界 |
| Modify | backend/app/api/routers/audit.py | 正式审计范围 |
| Modify | backend/app/api/routers/audit_export.py | 正式导出范围 |
| Modify | backend/app/api/routers/operations.py | 部门可见的脱敏运行信息 |
| Modify | backend/app/api/routers/threads.py | 正式会话、确认和线程归属 |
| Modify | backend/app/api/routers/interrupts.py | 服务端确认及恢复校验 |
| Modify | backend/app/api/routers/tickets.py | builtin 分派到正式服务，旧模式保留 |
| Modify | backend/app/services/ticket_service.py | legacy 边界，正式不回退及修复幂等语义 |
| Modify | backend/app/graph/nodes/leave_nodes.py | 正式请假预检/写入/对账/通知 |
| Modify | backend/app/graph/nodes/ticket_nodes.py | 正式工单确认、写入和对账 |
| Modify | backend/app/graph/nodes/faq_nodes.py | 正式知识检索与生成前复核 |
| Modify | backend/app/graph/graph_service.py | 恢复时最新身份和权威结果查询 |
| Modify | backend/app/tools/knowledge_tools.py | 来源范围和受限返回 |
| Modify | backend/app/services/document_service.py | 文档来源、生成和下载复核 |
| Modify | backend/app/services/email_service.py | 草稿来源与人工发送边界回归 |
| Modify | backend/app/services/meeting_service.py | 会议内容与派生任务权限 |
| Modify | backend/app/services/work_task_service.py | 正式指派与来源权限 |
| Modify | backend/app/services/report_service.py | 正式快照/缓存/导出复核 |
| Modify | backend/app/services/report_query.py | 正式工单/审批统计与范围谓词 |
| Modify | backend/app/services/contract_service.py | 合同文件、分析和任务来源复核 |
| Modify | backend/app/main.py | 正式路由和生命周期注册 |
| Modify | backend/app/models/__init__.py | 注册新增模型供迁移/测试使用 |
| Modify | backend/app/api/routers/auth.py | 返回报销/工单/通知可用能力 |
| Create | frontend/src/views/OAReimbursementsView.vue | 报销草稿、发票、历史及重提 |
| Create | frontend/src/views/OATicketsView.vue | 本人工单、重复候选及处理列表 |
| Create | frontend/src/views/OANotificationsView.vue | 站内信、投递状态和获授权核对 |
| Modify | frontend/src/views/OAApprovalsView.vue | 请假/报销审批上下文 |
| Modify | frontend/src/views/OAWorkflowView.vue | 受限报销字段和金额分支配置 |
| Modify | frontend/src/views/OAAdministrationView.vue | 报销转交、恢复和对账 |
| Modify | frontend/src/views/OrganizationView.vue | 新权限中文显示 |
| Modify | frontend/src/api/oa.ts | 正式业务与确认 API |
| Modify | frontend/src/types/oa.ts | 有类型的主体、金额、工单和渠道状态 |
| Modify | frontend/src/utils/oa.ts | 中文显示和稳定命令键 |
| Modify | frontend/src/stores/auth.ts | 新能力及权限路由映射 |
| Modify | frontend/src/router/index.ts | 新正式入口保护 |
| Modify | frontend/src/App.vue | 中文菜单和收件入口 |
| Create | backend/scripts/m3_preview.py | 专用本地身份、库、文件和随机凭证 |
| Create | backend/scripts/m3_verify.py | 固定库白名单、环境检查和串行验收入口 |
| Create | backend/tests/migrations/test_builtin_business_migration.py | 0024 含数据升级及新约束 |
| Create | backend/tests/unit/test_oa_money_definition.py | 金额精度、字段和阈值边界 |
| Create | backend/tests/api/test_oa_reimbursement.py | 报销生命周期及发票 |
| Create | backend/tests/api/test_oa_ticket.py | 创建/合并/办理/反馈 |
| Create | backend/tests/api/test_oa_notifications.py | 入箱/已读/联系配置和状态 |
| Create | backend/tests/contracts/test_builtin_gateway.py | C01-C13、A01/A02 及错误/对账 |
| Create | backend/tests/security/test_m3_scope.py | 直接服务、工具、管理、来源和越权 |
| Create | backend/tests/integration/test_m3_atomicity.py | 命令/审计/outbox 故障回滚 |
| Create | backend/tests/integration/test_m3_concurrency.py | 审批/合并/领取/投递多进程竞争 |
| Create | backend/tests/recovery/test_m3_replay.py | 确认、图检查点和权威重放 |
| Create | backend/tests/integration/test_m3_smtp.py | 本机 SMTP 捕获、超时与未知恢复 |
| Create | backend/tests/integration/test_m3_p2_p3.py | 正式来源、缓存和导出权限 |
| Create | backend/tests/integration/test_m3_ai_disabled.py | AI 关闭的完整人工闭环 |
| Create | frontend/src/tests/oa-reimbursement.test.ts | 金额/附件/保存冲突/重提 |
| Create | frontend/src/tests/oa-ticket.test.ts | 确认/合并/领取及错误 |
| Create | frontend/src/tests/oa-notification.test.ts | 渠道状态和未知核对 |
| Create | frontend/e2e/m3-business.spec.ts | 桌面与手机人工及智能确认流程 |
| Create | frontend/playwright.m3.config.ts | M3 专用端口和证据目录 |
| Modify | frontend/playwright.config.ts | 默认旧套件排除独立 M3 用例 |
| Create | docs/m3-business-acceptance.md | 实际运行证据、限制及人工验收入口 |
| Modify | docs/real-oa-bridge.md | 纠正计数、工单对账和辅助读契约 |
| Modify | README.md | 新阶段入口与真实进度 |
| Modify | docs/部门OA正式化实施计划-V1.1.md | 阶段进度入口，不追改历史证据 |
| Modify | OA智能体管理系统-正式PRD-V1.5.md | 实施状态及原始桥接盘点更正 |

现有策略路由、工具注册和读工具调用点在 B4/B5 清单中逐个记录实际路径；新增遗漏入口若仅为上述行为内的同类授权补齐可纳入清单，若改变能力或表结构则回到契约。本目录七份规划文件和 reviews/B1.md 至 B7.md、reviews/verification.md 为人工记录；截图、日志、测试附件和凭证仅存忽略目录 data/verification/m3/。

## Interfaces

| 批次 | Consumes | Produces |
| --- | --- | --- |
| B1 | M1 CurrentUser/动态授权、M2 OACommand/CommandOutcome 和 0024 | OAWorkflowSubject；scene 约束与共用审批引擎；0025 |
| B2 | B1 主体与命令、私有文件验证 | ReimbursementFields；amount_minor:int；正式报销 API |
| B3 | B1 OACommand/CommandOutcome | FormalTicketCommand、TicketResult、BridgeConfirmation、BridgeResult；0026 |
| B4 | B1 事件/outbox、B3 幂等结果 | NotificationReceipt、DeliveryStatus；C12/C13；0027 |
| B5 | B1-B4 正式命令、确认及通知 | BridgeContext、异步 OAGateway；C01-C13+A01/A02；0028；来源过滤/正式策略审计 |
| B6 | B2-B5 DTO、能力与权限清单 | 中文工作台和稳定确认/重试交互 |
| B7 | B1-B6、两专用数据库、Mock 模型/嵌入 | 迁移/联合/浏览器证据与验收文档 |

BridgeContext 的 actor 必须由会话恢复，confirmation_id 由正式确认服务读取；网关不持有全局用户。所有领域函数为 async def (session: AsyncSession, actor: CurrentUser, ...)->CommandOutcome 或明确只读 DTO，最终提交由调用者控制。业务对账结果与 NotificationReceipt 的渠道状态不能混用。

## Execution Tasks

每项任务按下面列出的五个阶段推进；每个阶段再按单个 WHEN/THEN 场景迭代，单次读码、写一个失败断言、实现最小改动、跑定向测试或记录结果各为约 2-5 分钟的原子步骤。完整批次不承诺在 5 分钟内完成，不以运行失败命令替代真实 RED。没有数据库服务时可继续不依赖数据库的规格和代码工作，但不能跳过必须的集成证据。

### 1. B1 类型化流程底座

Depends on：本阶段契约批准、专用库批准、人工计划有效。Covers M3-03/M3-09/M3-14。

Interfaces：Consumes M2 OACommand/CommandOutcome；Produces OAWorkflowSubject 和 0025。

1. 读取 models/oa_workflow.py 与 services/oa_approval_service.py、oa_handoff_service.py、oa_workflow_scheduler.py，列出所有 leave_version_id 关联及原行为。
2. 在 tests/migrations/test_builtin_business_migration.py 写 0024 含数据升级及非法双关联 RED；在原 M2 审批用例增加主体兼容失败断言。
3. 实现 0025、models/oa_reimbursement.py、services/oa_workflow_subject.py 和共用审批/转交/调度解析；原请假余额钩子保持。
4. 跑迁移约束、M2 原审批/余额/并发/转交/调度定向回归为 GREEN；补事件 trace/版本/差异故障回滚测试。
5. 扫描剩余直接 leave join，复核约束和旧数据保持，记录 reviews/B1.md；通过后进入 B2。

### 2. B2 报销与发票

Depends on：B1 通过。Covers M3-03/M3-04/M3-05/M3-09。

Interfaces：Consumes OAWorkflowSubject；Produces ReimbursementFields、amount_minor 和报销 API。

1. 对 schemas/oa_workflow.py 与 services/oa_attachment_service.py 读取金额条件/附件复用边界。
2. 在 unit/test_oa_money_definition.py、api/test_oa_reimbursement.py 写金额上下/等于边界、非法精度、无发票和越权 RED。
3. 实现 schemas/oa_reimbursement.py、services/oa_reimbursement_service.py、oa_reimbursement_attachment_service.py 与 api/routers/oa_reimbursements.py；发布模板固定金额规则。
4. 定向验证保存/提交/会签/或签/驳回重提/撤回/归档、转交、模板变化及附件完整性为 GREEN；注入 outbox/审计失败证明回滚。
5. 实施者复核金额不经 float、批准无付款、扫描未配置拒绝，记录 reviews/B2.md。

### 3. B3 正式工单与可信确认

Depends on：B1、B2 通过，串行执行。Covers M3-06/M3-09/M3-10。

Interfaces：Consumes OACommand/CommandOutcome；Produces FormalTicketCommand、确认/结果持久化和 0026。

1. 对 ticket_service.py、schemas/ticket.py 和 graph/nodes/ticket_nodes.py 盘点旧确认和幂等缺口，明确正式表隔离。
2. 在 api/test_oa_ticket.py、integration/test_m3_concurrency.py、recovery/test_m3_replay.py 写目标变更、并发领取、伪造/过期确认及重复消费 RED。
3. 实现 0026、models/oa_ticket.py、oa_bridge.py、services/oa_ticket_service.py、oa_confirmation_service.py、schemas/oa_ticket.py 和 routers/oa_tickets.py；确认消费/领域写/结果同事务。
4. 跑创建、候选确认合并、分派、领取、办理、反馈重开、同键重放/异载荷/失权及原子性测试为 GREEN；旧 Mock 表保持。
5. 复核无管理员角色旁路、无图状态授权、合并目标/version 进入 payload hash，记录 reviews/B3.md。

### 4. B4 通知持久化与投递

Depends on：B1-B3 通过。Covers M3-07/M3-08/M3-09。

Interfaces：Consumes 业务事件及有效对象；Produces NotificationReceipt、DeliveryStatus 和 0027。

1. 读取 OAWorkflowOutbox、scheduler.py、work_task_scheduler.py，列出事件/提醒来源及终态取消条件。
2. 在 api/test_oa_notifications.py、integration/test_m3_smtp.py 写重复入箱、发送前失权、暂时/永久失败、受理后断连和重启租约 RED。
3. 实现 0027、models/schemas/oa_notification.py、providers/smtp.py、services/oa_notification_service.py、oa_notification_worker.py、routers/oa_notifications.py 和调度接入。
4. 使用本机 SMTP 捕获服务及多进程 worker 验证 GREEN：唯一入箱、失败重试、UNKNOWN 不自动重发、终态取消、已读权限；验证业务不因渠道失败回滚。
5. 复核无外发、无正文/凭据泄漏、SMTP 受理未冒充送达；记录 reviews/B4.md。

### 5. B5 内桥、知识与 P2/P3

Depends on：B1-B4 通过。Covers M3-01/M3-02/M3-09/M3-10/M3-11/M3-12。

Interfaces：Consumes 前四批全部权威服务；Produces BridgeContext/OAGateway、C01-C13+A01/A02 和 0028。

1. 建立 reviews/m3-entrypoint-inventory.md：列 API/直接服务/工具/图/恢复/调度/预览/导出/策略管理和每个 get_adapter 调用的实际文件、权限、来源和状态。
2. 在 contracts/test_builtin_gateway.py、security/test_m3_scope.py、integration/test_m3_p2_p3.py 写缺能力、跨租户、失权、来源下架、旧 chunk 回退、聚合/缓存泄漏及结果对账 RED。
3. 实现 gateway.py、builtin_gateway.py、bundle/base/factory/adapter 扩展、0028 和 models/oa_ai_scope.py、services/oa_scope_service.py；将图/工具迁移为可信上下文；逐个完成知识/策略/审计/报表/P2/P3 的范围过滤再开放对应 deps。
4. 跑核心/辅助契约逐项错误/幂等/对账及 Mock/real 兼容为 GREEN；恢复已提交业务的图，确认无重复写入；运行 6 个 P2/P3 场景的来源/导出/调岗复核。
5. 对照入口清单扫描漏接同步调用、旧表 fallback 和全局角色绕过；所有 M3 必需入口必须通过，记录 reviews/B5.md，不以留存 503 代替必须能力交付。

### 6. B6 中文工作台与交互

Depends on：B1-B5 通过。Covers M3-10/M3-13。

Interfaces：Consumes 正式 DTO、确认/幂等 API；Produces 报销/工单/消息页面与新版审批/流程配置。

1. 读取既有 OA 页面、api/oa.ts、types/oa.ts、auth/store/router；按本次实际交互应用项目 UI 技能，保留 Element Plus 约定。
2. 在 oa-reimbursement.test.ts、oa-ticket.test.ts、oa-notification.test.ts 写金额、失效确认、重试键、保存时并发编辑、未知投递状态和失权 RED。
3. 实现 OAReimbursementsView.vue、OATicketsView.vue、OANotificationsView.vue；扩展 OAApprovals/Workflow/Administration、中文资源、能力菜单和前端 API/类型。
4. 定向组件测试至 GREEN、运行类型/构建；浏览器检查桌面与 390px 的发票上传、操作对话框、金额分支及通知核对。
5. 复核状态/错误中文、无误报成功、无重复提交与文字遮挡；记录 reviews/B6.md。

### 7. B7 联合验证与交付

Depends on：B1-B6 通过。Covers M3-01 至 M3-14，重点 M3-14。

Interfaces：Consumes 已完成实现与批次证据；Produces 独立预览、联合报告和验收入口。

1. 实现 scripts/m3_preview.py、m3_verify.py 与 playwright.m3.config.ts；先核验三地址/两个批准库/端口，Mock 模型/嵌入、随机账号和独立存储；误用库写失败断言。
2. 在 integration/test_m3_ai_disabled.py、recovery/test_m3_replay.py、frontend/e2e/m3-business.spec.ts 写端到端人工/确认/恢复用例；已有代码直接通过时记录集成验证，不伪造 RED。
3. 串行运行 0024 至 0028 迁移、后端联合套件、前端全套/构建、桌面/手机浏览器；只有失败或新增更改才重复相关验证。
4. 复核原 M2 数据保持、AI 关闭可办、禁用/调岗、并发、故障回滚、SMTP 未知恢复、Mock 历史隔离、C01-C13+A01/A02；修复后复验。
5. 写 reviews/B7.md、reviews/verification.md、docs/m3-business-acceptance.md，按真实结果更新 README/实施计划/PRD；保留所有旧报告和 .env，不声明生产验收完成。

## Requirement Coverage

| 需求 | 实施批次 | 必须证据 |
| --- | --- | --- |
| M3-01 | B5/B7 | API、服务、工具、恢复最新身份及无 Mock 回退 |
| M3-02 | B3/B5/B7 | 13 核心+2 辅助；同键/异载荷/只读对账 |
| M3-03 | B1/B2/B7 | 0024 旧实例保持、双关联拒绝、版本固定 |
| M3-04 | B2/B7 | 分值精度/三边界/生命周期/无付款 |
| M3-05 | B2/B7 | 发票权属、扫描、丢失/篡改、下载权限 |
| M3-06 | B3/B7 | 合并目标、分派/领取竞争、反馈重开 |
| M3-07 | B4/B7 | 本机 SMTP、租约、重试、UNKNOWN |
| M3-08 | B4/B7 | 当前席位/终态/调岗/去重/最小邮件 |
| M3-09 | B1-B5/B7 | 审计/outbox 故障回滚、脱敏及 trace |
| M3-10 | B3/B5/B6/B7 | 可信确认、版本失效、检查点恢复 |
| M3-11 | B5/B7 | 检索前过滤/生成前复核/文档指令无权 |
| M3-12 | B5/B7 | 6 场景来源/缓存/聚合/导出/管理范围 |
| M3-13 | B6/B7 | 中文、AI 关闭、桌面/手机及重复点击 |
| M3-14 | B1-B7 | 库白名单、串行测试、真实逐批与联合报告 |
