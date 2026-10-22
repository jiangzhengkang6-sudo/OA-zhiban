# M2 文件级任务

状态：2026-10-19，用户已批准的 B1–B6 本地工程实施、验证和实施者复核完成。最终后端 608 项通过（明确排除 1 项额外建库的历史迁移测试）、前端 87 项、浏览器 6 项通过，构建通过，见 [联合验证](reviews/verification.md)。各项真实 Red/Green 与修复记录见逐批报告，不补造测试先后。

## File Structure

路径均相对项目根目录；Create 是拟新增文件，Modify 是拟修改的既有文件。

| 操作 | 路径 | 责任 |
| --- | --- | --- |
| Create | backend/migrations/versions/0024_manual_oa_workflow.py | 仅扩张正式 OA 表及约束，父版本 0023 |
| Create | backend/app/models/oa_workflow.py | 流程定义/版本、实例、节点/席位、操作、事件、outbox 八表 |
| Create | backend/app/models/oa_leave.py | 单据/版本、余额/台账、私有附件五表 |
| Modify | backend/app/models/__init__.py | 注册正式模型 |
| Create | backend/app/schemas/oa_workflow.py | 有限 DSL、决定/转交/恢复、节点读取及对账 DTO |
| Create | backend/app/schemas/oa_leave.py | 草稿/提交/余额/附件和申请人读取 DTO |
| Create | backend/app/services/oa_access_service.py | 正式身份、部门范围、节点上下文及最新资格 |
| Create | backend/app/services/oa_command_service.py | 统一锁序、操作键、载荷哈希、审计和 outbox，无内部提交 |
| Create | backend/app/services/oa_workflow_service.py | DSL 校验、发布、版本查询、确定性路线解析 |
| Create | backend/app/services/oa_leave_service.py | 草稿、提交、重提、撤回、归档和受限读取 |
| Create | backend/app/services/oa_balance_service.py | 年度账户、跨年拆分及精确占用/扣减/释放 |
| Create | backend/app/services/oa_attachment_service.py | 正式附件归属、私有字节存储、扫描和版本清单 |
| Create | backend/app/services/oa_approval_service.py | 顺序/会签/或签决定、待办/已办/抄送投影 |
| Create | backend/app/services/oa_handoff_service.py | 管理员逐席代理、转交和固定版本恢复 |
| Create | backend/app/services/oa_workflow_scheduler.py | 正式有效节点催办/升级与只读对账 |
| Create | backend/app/api/routers/oa_leaves.py | /oa/leaves 单据与私有材料接口 |
| Create | backend/app/api/routers/oa_approvals.py | /oa/approvals 节点决定和最小上下文 |
| Create | backend/app/api/routers/oa_workflows.py | /oa/workflows 配置/发布/版本 |
| Create | backend/app/api/routers/oa_balances.py | /oa/balances 本人/部门余额及授权调整 |
| Create | backend/app/api/routers/oa_administration.py | /oa/administration 暂停列表/逐席管理/对账 |
| Modify | backend/app/api/deps.py | 显式接入正式路由授权；保留旧接口拦截 |
| Modify | backend/app/api/routers/auth.py | 返回无敏感信息的人工 OA/AI 能力标志 |
| Modify | backend/app/services/organization_service.py | 增加可分配资源，不自动扩大现有角色权限 |
| Modify | backend/app/services/authorization_service.py | AI 关闭工具保护，保留正式节点专用授权边界 |
| Modify | backend/app/services/scheduler.py | 接入独立正式调度，AI 关闭不阻断人工调度 |
| Modify | backend/app/core/config.py | AI_ENABLED，默认保持现有智能功能 |
| Modify | backend/app/main.py | 路由注册及图运行期按开关初始化/关闭 |
| Modify | .env.example | 仅记录 AI_ENABLED 的非敏感说明，不触碰真实 .env |
| Create | backend/tests/migrations/test_manual_oa_migration.py | 空库/0023 带数据升级及租户约束 |
| Create | backend/tests/unit/test_oa_workflow_definition.py | DSL、版本、字段类型和确定性分支 |
| Create | backend/tests/security/test_oa_workflow_access.py | 直接服务/路由/节点/附件/调岗及跨租户授权 |
| Create | backend/tests/api/test_oa_workflow_configuration.py | 流程发布、权限及版本固定 |
| Create | backend/tests/api/test_oa_leave_lifecycle.py | 草稿、提交、重提、撤回、归档和关键字段退回 |
| Create | backend/tests/api/test_oa_leave_attachments.py | 真引用、扫描、完整性、版本和下载边界 |
| Create | backend/tests/api/test_oa_leave_balances.py | 管理调整、跨年、无账户及台账 |
| Create | backend/tests/integration/test_oa_workflow_concurrency.py | 独立会话/进程的余额、或签、撤回与幂等竞争 |
| Create | backend/tests/api/test_oa_approval_modes.py | 单签/会签/或签、已办/抄送 |
| Create | backend/tests/api/test_oa_workflow_handoff.py | 停用转交、代理、路线修订及原人失效 |
| Create | backend/tests/recovery/test_oa_workflow_recovery.py | 调度去重、重启、终态竞争和只读对账 |
| Create | backend/tests/integration/test_oa_workflow_atomicity.py | 审计/outbox/台账失败的全事务回滚 |
| Create | backend/tests/integration/test_ai_disabled_manual_oa.py | AI 关闭、不初始化图且人工完整办理 |
| Create | backend/tests/integration/test_m2_identity_mock_compatibility.py | M1、旧显式 Mock 和新接口隔离 |
| Create | frontend/src/types/oa.ts | 正式人工 DTO，不混用旧 ThreadDetail |
| Create | frontend/src/api/oa.ts | 五类正式接口及操作键 |
| Create | frontend/src/utils/oa.ts | 中文状态/原因/日期显示及命令重试键 |
| Create | frontend/src/views/OALeavesView.vue | 我的申请及申请人草稿/历史 |
| Create | frontend/src/views/OAApprovalsView.vue | 待办/已办/抄送及节点最小上下文 |
| Create | frontend/src/views/OAWorkflowView.vue | 结构化流程/表单/规则配置、发布和版本 |
| Create | frontend/src/views/OABalancesView.vue | 本人额度及授权部门调整 |
| Create | frontend/src/views/OAAdministrationView.vue | 暂停原因、待交接、逐席代理/转交/恢复和对账 |
| Modify | frontend/src/stores/auth.ts | 能力标志和 /oa 子路由资源映射 |
| Modify | frontend/src/router/index.ts | 正式页面路由及直达保护 |
| Modify | frontend/src/App.vue | 正式业务菜单和 AI 可用状态 |
| Modify | frontend/src/views/OrganizationView.vue | 新权限资源的中文展示 |
| Create | frontend/src/tests/oa-leave-workbench.test.ts | 草稿/提交/重试/会话隔离及自然语言显示 |
| Create | frontend/src/tests/oa-approval-workbench.test.ts | 席位/状态操作及最小上下文显示 |
| Create | frontend/src/tests/oa-administration.test.ts | 流程/额度/转交表单、权限及错误状态 |
| Create | frontend/e2e/m2-manual-oa.spec.ts | 桌面/手机完整人工闭环 |
| Create | frontend/playwright.m2.config.ts | M2 独立服务/端口及浏览器证据目录 |
| Modify | frontend/playwright.config.ts | 默认旧套件排除 M2 隔离用例 |
| Create | backend/scripts/m2_preview.py | 独立预览库、随机测试身份/额度、AI 关闭，凭证仅存忽略目录 |
| Create | docs/m2-manual-oa-acceptance.md | 实际运行证据、人工验收和未交付边界 |
| Modify | README.md | M2 状态、入口和验收链接 |
| Modify | docs/部门OA正式化实施计划-V1.1.md | 按实际进度更新，不追改 M1 原始证据 |
| Modify | OA智能体管理系统-正式PRD-V1.5.md | 仅更新实施状态入口，不修改既定功能需求 |

本目录 proposal/specs/design/tasks/execution-contract/execution-plan/planning-status 及后续 reviews/B1.md 至 B6.md、reviews/verification.md 是规划/实施记录。测试临时数据、截图、运行日志和预览凭证仅存已忽略的 data/verification/m2/。不授权提交 Git、真实数据导入、生产部署或原库迁移。

## Interfaces

| 产出批次 | 精确契约 | 消费批次 |
| --- | --- | --- |
| B1 | `WorkflowDefinitionInput`、`PublishedWorkflowView`；`validate_definition(input: WorkflowDefinitionInput) -> ValidatedDefinition` | B2/B3/B4/B5 |
| B1 | `resolve_route(db: AsyncSession, actor: CurrentUser, version: OAWorkflowVersion, form: NormalizedLeaveFields) -> RoutePlan`，固定 nodes/seats/eligibility/pause_reasons | B2/B3/B4 |
| B1 | `authorize_oa(db: AsyncSession, actor: CurrentUser, resource: str, action: str, *, target: OAAccessTarget) -> OAAccessContext`；无通用 admin 旁路 | 全部后续批次 |
| B1 | `run_command(db: AsyncSession, actor: CurrentUser, command: OACommand, handler: Callable[..., Awaitable[CommandOutcome]]) -> CommandOutcome`；调用者最终 commit；键/载荷/结果同事务 | B2/B3/B4 |
| B2 | `LeaveDraftCreate(workflow_definition_id, fields)`、`LeaveDraftPatch(expected_revision)`、`SubmitLeaveCommand(expected_revision, requested_submission_version, operation_id)` | B3/B5 |
| B2 | `reserve/consume/release(db: AsyncSession, version: OALeaveVersion, command_id: UUID) -> list[BalanceMovementView]`，不自行 commit | B3/B4 |
| B2 | `LeaveApplicantDetail`、`LeaveVersionView`、`AttachmentView`、`BalanceView`，日期 ISO yyyy-mm-dd、整数天数、原始 status + 中文展示映射 | B3/B5 |
| B3 | `DecideNodeCommand(expected_revision, operation_id, action, reason_code, note, corrections, approval_note)`；action=approve/reject/return_for_correction | B4/B5 |
| B3 | `ApprovalNodeContext`、`ApprovalListItem`、`CommandOutcome(result, replayed, current_revision, allowed_actions)`；上下文不含完整他轮材料/账户 | B4/B5 |
| B4 | `SeatHandoffCommand(expected_revision, operation_id, target_user_id, reason)`、`RouteResumeCommand(expected_revision, operation_id, replacements, reason)`、`ReconciliationReport` | B5/B6 |
| B5 | `/auth/config` 增量 `capabilities: {manual_oa: bool, ai_enabled: bool}`；`/api/oa/*` 全部沿用 ApiResponse，新增契约不改变旧响应 | B6 |

## 1. B1 结构、授权、命令和发布

Depends on: M1 已完成且本轮契约获批准。Covers M2-01、M2-02、M2-07、M2-09、M2-12 的公共基座。

- [x] 1.1 类型与有限 DSL。Red：在 test_oa_workflow_definition.py 逐项写环/未知字段/无默认分支/类型边界断言。验证 Red：逐场景运行确认缺行为。Green：创建 schemas/oa_workflow.py、schemas/oa_leave.py 及 oa_workflow_service.py 的纯校验器。验证 Green：覆盖合法路径及 Decimal 相等/阈值两侧。Refactor：统一规范化及中文校验错误。Interfaces：Consumes PRD；Produces ValidatedDefinition/NormalizedLeaveFields。
- [x] 1.2 数据结构。Red：test_manual_oa_migration.py 写 0023 哨兵数据、跨租户 FK、余额 CHECK、键唯一断言。验证 Red：隔离库确认 0024 缺失/约束缺失。Green：创建 models/oa_workflow.py、oa_leave.py、0024_manual_oa_workflow.py，注册 models/__init__.py。验证 Green：空库及 0023 带数据升到 head、重复升级、旧数据保持。Refactor：核对 ORM 与迁移约束一致。Interfaces：Consumes 1.1；Produces 13 张正式表及映射。
- [x] 1.3 授权与事务命令。Red：test_oa_workflow_access.py、test_oa_workflow_atomicity.py 写直接服务越权、异载荷及失败回滚场景。验证 Red：分别确认缺授权/事务行为。Green：实现 oa_access_service.py、oa_command_service.py，增加 organization_service.py 可分配资源及 api/deps.py 精确接入规则。验证 Green：跨租户/部门/节点、会话失效、审计/outbox 失败、同键同载荷和异载荷。Refactor：统一锁序，不提前 commit。Interfaces：Consumes 1.1/1.2；Produces authorize_oa/run_command。
- [x] 1.4 发布和解析。Red：test_oa_workflow_configuration.py 写版本固定、选择器去重、自审暂停及未发布拒绝。验证 Red：确认新发布入口/解析行为缺失。Green：完成 oa_workflow_service.py，创建 oa_workflows.py，并在 main.py 注册此路由。验证 Green：版本哈希、所有分支及组织变化不改路线。Refactor：区分发布结构错误和运行人员异常。Interfaces：Consumes 1.1–1.3；Produces PublishedWorkflowView/RoutePlan。

B1 完成条件：迁移/公共边界/发布测试通过，reviews/B1.md 保存检查与限制；后续不以“写了模型”替代约束验证。

## 2. B2 申请、材料、额度与提交

Depends on: Batch B1 审查通过。Covers M2-03、M2-04、M2-05、M2-07。

- [x] 2.1 草稿与材料。Red：test_oa_leave_lifecycle.py 和 test_oa_leave_attachments.py 写本人修订竞争、真引用、扫描及下载越权。验证 Red：逐项运行新断言。Green：创建 oa_leave_service.py 的草稿/读取、oa_attachment_service.py、oa_leaves.py。验证 Green：PENDING/ERROR/哈希变化拒绝、历史清单不变及转交后原人失去下载权（转交联合场景在 B4 补完）。Refactor：复用既有扫描协议，正式归属校验不调用旧 task 权限。Interfaces：Consumes B1；Produces LeaveApplicantDetail/AttachmentView。
- [x] 2.2 额度和日历日。Red：test_oa_leave_balances.py 写同日/跨年/缺账户/调整下限，test_oa_workflow_concurrency.py 写不同假种重叠及额度竞争。验证 Red：独立数据库会话确认失败点。Green：创建 oa_balance_service.py、oa_balances.py，实现人员锁、年度锁与台账。验证 Green：检查 total/used/reserved 和每条账，失败跨年不部分占用。Refactor：整天整数计算，不用 float。Interfaces：Consumes B1；Produces reserve/consume/release、BalanceView。
- [x] 2.3 提交与重提。Red：test_oa_leave_lifecycle.py 写材料失败无版本、无路线 PAUSED 占用、驳回新轮、丢响应重试；atomicity 测试增加提交故障注入。验证 Red：逐路径确认缺行为。Green：完成 oa_leave_service.py 提交、快照、预检和稳定命令键。验证 Green：固定版本/附件、跨年整体提交、同键并发单实例，B3 完成后联合重提复验。Refactor：去除 Provider/图依赖，记录三类修订。Interfaces：Consumes B1 和 2.1/2.2；Produces SubmitLeaveCommand/LeaveVersionView。

B2 完成条件：新人工申请可以确定性占用，全部失败路径无半成品；reviews/B2.md 通过后进入 B3。

## 3. B3 审批决定与状态机

Depends on: Batch B2 审查通过。Covers M2-06、M2-07、M2-08、M2-09、M2-12。

- [x] 3.1 三种审批模式。Red：test_oa_approval_modes.py 写单签顺序、会签全同意/任一驳回、或签竞争；concurrency/atomicity 增加最后决定竞争及故障注入。验证 Red：确认未实现行为。Green：创建 oa_approval_service.py、oa_approvals.py，连接余额结算、事件和操作结果。验证 Green：终态只一次、后到操作当前状态、重放不重复扣减。Refactor：统一节点推进，无进程内唯一性假设。Interfaces：Consumes B1/B2；Produces DecideNodeCommand/CommandOutcome。
- [x] 3.2 撤回、退回修改和归档。Red：test_oa_leave_lifecycle.py 写撤回/批准竞争、关键字段编辑拒绝、结构化退回重提和归档保留结果。验证 Red：逐动作运行。Green：完成 oa_leave_service.py、oa_approval_service.py 的相应状态转换。验证 Green：重提重新路由/占用，历史只读，归档不返还额度。Refactor：分离状态/outcome/archived_at。Interfaces：Consumes 3.1；Produces 完整生命周期和 allowed_actions。
- [x] 3.3 最小上下文和列表。Red：test_oa_workflow_access.py、test_oa_approval_modes.py 写当前节点材料、历史仅摘要、抄送无决定权及跨部门不能列他人申请。验证 Red：确认投影和过滤缺失。Green：完成 oa_access_service.py、oa_approval_service.py 的待办/已办/抄送及节点详情。验证 Green：列表、详情、附件同范围；无隐藏敏感字段。Refactor：申请人和节点 DTO 明确分开。Interfaces：Consumes B2/3.1；Produces ApprovalNodeContext/ApprovalListItem。

B3 完成条件：完整人工状态机、事务失败和真实数据库竞争测试通过；reviews/B3.md 通过。

## 4. B4 转交、升级与恢复

Depends on: Batch B3 审查通过。Covers M2-09、M2-10、M2-11、M2-12。

- [x] 4.1 管理员逐席操作。Red：test_oa_workflow_handoff.py 写禁用转交、自审/重复会签/跨租户拒绝和旧页面失权。验证 Red：逐种资格运行。Green：创建 oa_handoff_service.py、oa_administration.py，实现理由、路线修订和 M2 交接范围结果。验证 Green：不动历史决定、不套新模板、不清除全业务 handoff_pending，下载权限同步失效。Refactor：代理/转交共享资格校验，禁止链式委托。Interfaces：Consumes B1/B3；Produces SeatHandoffCommand/RouteResumeCommand。
- [x] 4.2 正式调度。Red：test_oa_workflow_recovery.py 写多调度器认领、终态竞争、无合法上级暂停及重启补扫。验证 Red：显式控制时钟与两会话竞争。Green：创建 oa_workflow_scheduler.py，修改 scheduler.py 接入不依赖 AI 的正式扫描。验证 Green：去重事件、每席一次升级、截止时间规则和终态无新增有效催办。Refactor：单个单据失败不阻塞整批且不吞审计失败。Interfaces：Consumes B1/B3/4.1；Produces 持久化提醒/升级/异常事件。
- [x] 4.3 对账和故障恢复。Red：recovery/atomicity 测试写台账不一致、事务中断、进程重启后原键查询。验证 Red：确认报告/恢复缺失。Green：完成 oa_workflow_scheduler.py 只读对账和 oa_administration.py 报告，拒绝以图状态补业务。验证 Green：原操作安全重放，不自动改账，所有故障点整体回滚。Refactor：报告脱敏且按租户/部门授权。Interfaces：Consumes B1–B4；Produces ReconciliationReport。

B4 完成条件：停用转交、后台权限、并发调度和重启证据完整；reviews/B4.md 通过。

## 5. B5 AI 开关与中文工作台

Depends on: Batch B4 审查通过。Covers M2-01、M2-13，以及各业务规格的人工入口。

- [x] 5.1 启动与能力标志。Red：test_ai_disabled_manual_oa.py 写图初始化/模型/外部 OA 调用即失败条件下人工闭环，确认智能入口不可用且检查点不删。验证 Red：使用独立进程配置，不依赖全局 import 缓存。Green：修改 config.py、main.py、scheduler.py、authorization_service.py、api/deps.py、auth.py 和 .env.example。验证 Green：AI 开/关 + builtin/Mock 入口矩阵和独立进程人工闭环 4 项通过，纳入最终 608 项联合回归。Refactor：仅初始化过的运行期才关闭。Interfaces：Consumes B1–B4；Produces capabilities。
- [x] 5.2 申请人与审批人工作台。Red：oa-leave-workbench.test.ts、oa-approval-workbench.test.ts 写草稿修订、同载荷重试、权限变化、状态动作及节点最小投影。验证 Red：定向运行确认失败；补充延迟创建中继续编辑的重复建单失败。Green：创建 types/oa.ts、api/oa.ts、utils/oa.ts、OALeavesView.vue、OAApprovalsView.vue，修改 auth.ts、router/index.ts、App.vue，保存持久化 ID 并保留未保存编辑。验证 Green：工作台三组定向 11 项及前端全套 87 项通过，类型构建通过，不把其他轮材料拼回节点上下文。Refactor：沿用现有组件/图标和中文标签，普通用户无 JSON 编辑。Interfaces：Consumes B2/B3/capabilities；Produces 员工人工页面。
- [x] 5.3 管理工作台。Red：oa-administration.test.ts 写结构化流程编辑/发布冲突、额度调整、代理/转交/暂停恢复和无权直达；补充目标账户未就绪时保存按钮的失败场景。Green：创建 OAWorkflowView.vue、OABalancesView.vue、OAAdministrationView.vue，修改 OrganizationView.vue 的资源中文映射及相应导航，统一额度读取就绪门禁。验证 Green：工作台定向 11 项、前端全套 87 项与构建通过；隔离后端、桌面/手机浏览器验收通过。Refactor：实施界面前应用适用 UI 技能；检查移动端布局和错误状态。Interfaces：Consumes B1/B2/B4；Produces 管理入口。

B5 完成条件：关闭 AI 的人工入口全部可达、操作与服务一致；reviews/B5.md 通过。

## 6. B6 联合验收与交付

Depends on: Batch B5 审查通过。Covers M2-01 至 M2-13 全部联合验证。

- [x] 6.1 隔离回归。Red：test_m2_identity_mock_compatibility.py 增加新路由拒绝 Mock 身份、M1 权限资源不自动扩张、旧 Mock 行为保持；m2-manual-oa.spec.ts 写桌面/手机完整场景。验证 Red：显式核对数据库 URL 与预览进程，记录真实失败。Green：创建 m2_preview.py、playwright.m2.config.ts，修改默认 playwright.config.ts 排除 M2，用独立库/端口测试。验证 Green：后端联合回归 608 项通过（排除 1 项额外建库历史测试）、前端全套 87 项/构建、桌面/手机浏览器 6 项和截图通过，独立进程调度竞争通过。Refactor：迁移测试限定自身可逆范围，保留 0024 生产降级保护；不修改真实 .env/原库或放宽断言。Interfaces：Consumes B1–B5；Produces 原始验证证据。
- [x] 6.2 审查与交付文档。已复核各批实际测试、13 项规格及 PRD 覆盖，修复并复验保存/额度边界问题。真实命令、通过/失败、排除范围和限制记录于 reviews/B6.md、reviews/verification.md 和 docs/m2-manual-oa-acceptance.md，README、实施计划与 PRD 当前状态已同步。文档校验文件/链接与结果一致性，不补造 Red 顺序、Git SHA、机器 guard 或归档确认。Interfaces：Consumes 6.1；Produces 工程完成证据和 M3 输入。

## Requirement Coverage

| Requirement | PRD | Tasks | 主要验证 |
| --- | --- | --- | --- |
| M2-01 | F-152 人工/AI 部分 | 1.3、5.1、6.1 | test_ai_disabled_manual_oa、compatibility |
| M2-02 | F-110、F-131 请假部分 | 1.1、1.2、1.4、2.3 | definition、configuration |
| M2-03 | F-112、F-113 | 2.1、2.3、3.2 | lifecycle |
| M2-04 | F-120、6.2 余额规则 | 1.2、2.2、2.3、3.1、3.2 | balances、concurrency |
| M2-05 | F-120、7 数据安全 | 2.1、2.3、3.3、4.1 | attachments、access |
| M2-06 | F-111、6.2 会签/或签规则 | 1.4、3.1、3.3 | approval_modes、concurrency |
| M2-07 | F-113、F-114 | 1.2、1.3、2.3、3.1、4.3 | concurrency、atomicity、recovery |
| M2-08 | F-112、F-122 | 3.1、3.2 | lifecycle、concurrency |
| M2-09 | F-104/105/106 的业务延伸、F-115 | 1.3、3.3、4.1、4.2 | access、handoff |
| M2-10 | F-107、F-111、F-115 | 4.1、4.3 | handoff、recovery |
| M2-11 | F-111、F-114、F-115、F-141 | 4.2、4.3 | recovery、concurrency |
| M2-12 | F-114、F-150 | 1.3、2.3、3.1、4.2、4.3 | atomicity、recovery |
| M2-13 | F-121、F-152 人工入口 | 5.1、5.2、5.3、6.1、6.2 | frontend 三组测试、m2-manual-oa E2E |

未映射 M2 规格：无。明确分阶段：F-130 报销、F-140 消息/SMTP、F-152 本体故障补录、F-151 备份恢复不在本契约，不记为已交付。
