# P3 开发任务

状态：B1-B6 本地工程完成，Mock 工程验收 Pass；完成状态以 reviews/verification.md 的实际证据为准。人工及生产验收待完成。以下按最终实现路径修订，原五步过程为执行方法，不冒充逐步运行凭据。

| 批次 | 完成状态 | 验证依据 |
| --- | --- | --- |
| B1/B2 工作任务后端与工作台 | 本地完成 | T1-T5 映射、后端/前端/浏览器、独立样本及重启恢复 |
| B3/B4 只读报表后端与工作台 | 本地完成 | R1-R5 映射、真实只读查询、图表/发布及移动日期间距验证 |
| B5 私有合同与受限 DeepAgents | 本地完成 | C1-C5 映射、真实引擎/Mock、指定复核及重启恢复 |
| B6 联合验证与交付 | 本地完成 | 后端 420、前端 58、构建、浏览器 36、11 张 P3 截图、独立审查及交付文档 |

## File Structure

| 文件 | 操作与职责 |
| --- | --- |
| backend/app/models/work_task.py、work_task_batch.py、work_task_draft_version.py、work_task_event.py、work_task_notification.py | Create：独立任务、候选版本、业务事件及私有通知 |
| backend/app/models/report_record.py | Create：ReportRecord/ReportVersion、计划、数据/摘要快照、版本和发布记录 |
| backend/app/models/contract_record.py、contract_source.py、contract_review_version.py | Create：私有原文、来源位置、规则及审查版本 |
| backend/migrations/versions/0019_work_task_agent.py、0020_report_agent.py、0021_contract_agent.py、0022_work_task_reminder_fairness.py | Create：顺序增量迁移与索引/约束、提醒公平轮转 |
| backend/app/schemas/work_task.py、report.py、contract.py | Create：API、候选、计划、证据和命令 DTO |
| backend/app/services/work_task_service.py、work_task_generator.py、work_task_scheduler.py | Create：提取/确认/状态机/内部提醒 |
| backend/app/services/report_service.py、report_metrics.py、report_query.py、report_generator.py | Create：登记指标、只读查询、草稿/发布 |
| backend/app/services/contract_service.py、contract_parser.py、contract_rules.py、contract_deepagents.py | Create：输入、规则、证据校验、受限 DeepAgents 和人工复核 |
| backend/app/tools/work_task_tools.py、report_tools.py | Create：领域授权读取工具；合同读取工具封装在 contract_deepagents.py 内 |
| backend/app/graph/work_task_graph.py、report_graph.py、contract_graph.py | Create：三个独立 StateGraph 与可恢复节点 |
| backend/app/api/routers/work_tasks.py、reports.py、contracts.py | Create：专用资源路由 |
| backend/app/core/enums.py、config.py；backend/app/models/__init__.py；backend/app/main.py | Modify：场景、上限、注册及调度生命周期 |
| backend/app/graph/state.py、superagent.py、nodes/common.py；backend/app/tools/registry.py | Modify：显式场景注册与白名单，保留原路由 |
| backend/app/services/task_service.py、thread_service.py、interrupt_service.py、audit_service.py、runtime_trace_service.py | Modify：公共投影/旁路/审计/用量边界 |
| frontend/src/api/workTask.ts、report.ts、contract.ts；frontend/src/types/report.ts、contract.ts | Create：前端 API；任务 DTO 在 workTask.ts，报表和合同 DTO 在对应 types 模块 |
| frontend/src/views/WorkTaskView.vue、ReportView.vue、ContractView.vue | Create：三个业务工作台 |
| frontend/src/components/p3/MetricChart.vue；三个 Workbench 视图 | Create：结果图表；授权证据回链内联在各领域视图 |
| frontend/src/router/index.ts、App.vue、views/TaskCenterView.vue、ConfigView.vue、DegradationView.vue | Modify：导航、业务回链和场景开关 |
| backend/tests/unit/test_work_task_generator.py、test_p3_llm_budget.py、test_contract_parser.py、test_contract_recovery.py、test_contract_deepagents.py；backend/tests/test_report_rules.py | Create：确定性领域、恢复、预算与工具限制测试 |
| backend/tests/api/test_work_task_http.py、test_report_http.py、test_contract_http.py、test_p3_boundaries.py、test_p3_audit_isolation.py | Create：实际 API 生命周期及权限/事务/审计测试 |
| backend/tests/graph/test_p3_routing.py；backend/tests/migrations/test_p3_agents.py；backend/tests/evaluation/test_p3_work_task_evaluation.py、test_p3_report_evaluation.py、test_p3_contract_evaluation.py | Create：显式路由、增量迁移、独立评测；节点恢复在 unit/API 用例和重启脚本验证 |
| backend/tests/evaluation/p3_work_task_cases.json、p3_report_cases.json、p3_contract_cases.json | Create：各文件分开 development/acceptance，每场景各 6 个样本 |
| frontend/src/tests/work-task-workbench.test.ts、report-workbench.test.ts、contract-workbench.test.ts；frontend/e2e/p3-integration.spec.ts、playwright.p3.config.ts | Create：交互与实际后端桌面/移动回归 |
| backend/scripts/verify_p3_evaluation.py、verify_p3_restart.py | Create：可重跑评测证据和三个独立后端进程/两次重启恢复验证 |
| docs/p3-acceptance.md、changes/p3-business-agents/reviews/verification.md | Create：实测、局限与人工验收 |
| README.md、docs/api-contract.md、docs/functional-test-guide.md | Modify：最终能力、接口和手工用例 |

## Interfaces

B1 产生 WorkTaskSourceInput/WorkTaskCandidateDTO/WorkTaskBatchResponse/WorkTaskResponse/WorkTaskCommand；B2 消费并提供工作台。B3 产生 MetricDefinition/ReportPlan/MetricSnapshot/ReportResponse/ReportCommand；B4 消费并提供报表工作台。B5 产生 ContractInput/ContractEvidence/ContractRisk/ContractResponse/ContractCommand 及合同工作台。B6 消费全部接口和候选/规则/指标版本，产出实测验证记录。所有版本命令共享 idempotency_key/expected_version，分页维持现有 PageResult 结构。

## Execution Batches

每个以下编号任务包含五个顺序步骤：1. 在列明测试文件增加一项目标行为失败用例；2. 运行该项并确认失败原因；3. 在列明实现文件写最小通过实现；4. 运行该项及涉及既有边界测试；5. 审阅事务/权限/契约并记录证据。每一步按单项行为拆分为 2-5 分钟操作，不能将整个批次表示为 5 分钟。权限/恢复/迁移失败必须调查后再修复。

### B1 工作任务领域与后端（T1-T5）

Depends on：已记录的用户开发授权、本地执行计划及分支检查。

1.1 `test_work_task_http.py` / `work_task.py、work_task_batch.py、work_task_draft_version.py、0019_work_task_agent.py`：候选和业务任务独立持久化、唯一约束与版本。
1.2 `test_p3_boundaries.py` / `work_task_service.py、work_task_generator.py、work_task_tools.py`：三个来源读取、当前身份/来源检查、负责人校验、证据与风险门。
1.3 `test_work_task_http.py` / `work_task_service.py、work_task_event.py、work_tasks.py`：保存、确认、原子创建、幂等与进度/取消/归档状态机。
1.4 `test_work_task_http.py` / `work_task_scheduler.py、work_task_notification.py、main.py`：时间固定的两阶段内部提醒、竞态去重与调度失败隔离。
1.5 `test_p3_routing.py、test_p3_boundaries.py、verify_p3_restart.py` / `work_task_graph.py、state.py、superagent.py、task_service.py、thread_service.py、interrupt_service.py、registry.py`：图注册/恢复、任务投影和通用入口旁路拒绝。

Interfaces：Consumes 现有 MeetingResponse、TicketRecord、ApprovalInstance 和 CurrentUser；Produces 工作任务 DTO/API。完成定义：T1-T5 后端用例、迁移升级/拒绝非空降级、关闭 work_task 不影响 P1/P2。

### B2 工作任务工作台及独立验收（T1-T5）

Depends on：B1 测试通过并完成代码审查。

2.1 `work-task-workbench.test.ts` / `api/workTask.ts、WorkTaskView.vue`：来源选择、候选编辑、保存版本、风险二次确认和内联证据回链。
2.2 `work-task-workbench.test.ts` / `WorkTaskView.vue、TaskCenterView.vue、router/index.ts、App.vue`：任务列表/详情、角色动作、进度、提醒、脏编辑/请求键保护。
2.3 `test_p3_work_task_evaluation.py、test_work_task_http.py、p3-integration.spec.ts、verify_p3_restart.py` / `evaluation/p3_work_task_cases.json、playwright.p3.config.ts`：独立候选样本与 AT-01 至 AT-06 权限/事务/提醒边界分别验证，桌面/移动真实 API 创建/完成/归档，重启恢复与零外部发送。

Interfaces：Consumes B1；Produces /work-tasks/:id?。完成定义：独立样本通过、桌面/移动截图无溢出且功能正常；批次审查记录。

### B3 报表领域与只读后端（R1-R5）

Depends on：B2 验证/审查通过。

3.1 `test_report_rules.py、test_report_http.py、test_p3_report_evaluation.py` / `report_metrics.py、report_record.py、0020_report_agent.py、schemas/report.py`：固定指标口径、时间区间、计划和版本。
3.2 `test_p3_boundaries.py、test_report_http.py` / `report_query.py、report_tools.py、report_service.py`：范围过滤、计划批准、只读事务/超时、拒绝任意 SQL、范围失效。
3.3 `test_report_http.py` / `report_generator.py、report_service.py、reports.py`：真实快照、摘要引用/数字验证、失败暂停、编辑和平台发布。
3.4 `test_p3_routing.py、test_p3_boundaries.py、verify_p3_restart.py` / `report_graph.py、state.py、superagent.py、registry.py、task_service.py、thread_service.py、interrupt_service.py`：受控图恢复、幂等结果和旁路防护。

Interfaces：Consumes B1 业务任务及内置工单/审批数据；Produces 报表 DTO/API。完成定义：R1-R5、AR-01 至 AR-06 后端独立评测通过、只读事务证据、迁移与故障隔离审查。

### B4 报表工作台（R1-R5）

Depends on：B3 验证/审查通过。

4.1 `report-workbench.test.ts` / `api/report.ts、types/report.ts、ReportView.vue`：模板/指标/时间选择、计划审批、查询/重试与空数据状态。
4.2 `report-workbench.test.ts` / `MetricChart.vue、ReportView.vue`：真实指标图表、口径/时间/来源、异常候选、历史和人工平台发布。
4.3 `p3-integration.spec.ts` / `router/index.ts、App.vue、TaskCenterView.vue、ConfigView.vue、DegradationView.vue`：业务导航、开关、桌面/移动实际查询与发布/重启后重放。

Interfaces：Consumes B3；Produces /reports/:id?。完成定义：UI 测试、真实 API 浏览器、截图、报表独立禁用与审查通过。

### B5 合同输入、四节点和复核工作台（C1-C5）

Depends on：B4 验证/审查通过。

5.1 `test_contract_parser.py、test_contract_http.py` / `contract_record.py、contract_source.py、contract_review_version.py、0021_contract_agent.py、schemas/contract.py、contract_parser.py、contracts.py`：私有原文、hash/页码/偏移、TXT/PDF 类型与扫描门。
5.2 `test_p3_contract_evaluation.py、test_contract_http.py` / `contract_rules.py、contract_parser.py、contract_graph.py`：四类演示规则版本、提取、风险证据校验及注入防护。
5.3 `test_contract_recovery.py、test_contract_http.py、verify_p3_restart.py` / `contract_graph.py、contract_service.py、state.py、superagent.py`：四节点轨迹、限额、失败节点恢复、复核人身份和原子决定。
5.3a `test_contract_deepagents.py` / `contract_deepagents.py`：核实 DeepAgents 依赖/API、无付费模型烟测、长文档计划/分块读取、工具白名单和递归/调用/超时限制；四节点主图内部接入，异常不绕过。
5.4 `test_p3_boundaries.py` / `task_service.py、thread_service.py、interrupt_service.py、audit_service.py、registry.py`：正文/文件/checkpoint/重放 ACL、脱敏审计及终态只读。
5.5 `contract-workbench.test.ts、p3-integration.spec.ts` / `api/contract.ts、types/contract.ts、ContractView.vue、router/index.ts、App.vue、TaskCenterView.vue`：条款/风险/内联证据导航、逐项处理、指定复核与桌面/移动实际 API 交互。

Interfaces：Consumes 现有私有文件扫描门与 CurrentUser；Produces /contracts/:id?、合同 DTO/API。完成定义：C1-C5、AC-01 至 AC-06 工程样本通过；演示规则/真实法律质量界限明确；迁移/重启和审查通过。

### B6 联合验证、运行限额与交付（T5/R5/C5）

Depends on：B5 验证/审查通过。

6.1 `test_p3_boundaries.py、test_p3_routing.py、test_p3_llm_budget.py、test_contract_deepagents.py` / `config.py、runtime_trace_service.py、三个领域服务`：三场景调用/字数/输出/超时限额、实际/缺失 usage 标识、零付费调用及成本未知。
6.2 `test_p3_agents.py、evaluation/test_p3_*_evaluation.py、verify_p3_evaluation.py` / `0019/0020/0021/0022、evaluation/p3_*_cases.json`：迁移到 head、旧版本到 head、空 schema 往返、非空降级拒绝和独立样本。
6.3 全后端/前端/构建/浏览器 / `docs/p3-acceptance.md、reviews/verification.md`：完整 P1/P2 回归、三个场景独立关闭、真实重启恢复、桌面/移动截图；失败调查并修复后重跑受影响项。
6.4 文档核对 / `README.md、docs/api-contract.md、docs/functional-test-guide.md、reviews/verification.md`：记录实际命令与结果、API/手工用例、未完成生产条件；不制造 Git SHA、ssf 凭据或人工验收结果。

Interfaces：Consumes B1-B5；Produces 本地工程交付和真实验收待办。完成定义：所有映射用例通过、无未解决重要审查问题、预览可访问、生产局限明确。
