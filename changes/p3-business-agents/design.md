# P3 技术设计

## Context

现有 `/api/tasks` 和 `TaskCenterView.vue` 展示 `AgentThread` 流程投影。会议已保存不可变草稿和决定，但 action_items 不是工作任务。内置工单使用 `TicketRecord`，审批使用 `ApprovalInstance/ApprovalNode`。当前 `GraphRuntime` 通过 PostgreSQL Checkpointer 编译 SuperAgent，主图已有会议分支；文档/邮件主要通过资源服务驱动。现有 `idempotency_service`、`require_fresh_identity`、策略/降级/审计、runtime span/model usage 可复用。OAAdapter 没有工作任务/BI 能力，真实模型和企业侧接口尚无 P3 验收证据。

## Goals

实现三个独立本地业务闭环；不改变已有流程任务契约；每个结果都能追溯来源、版本和决定；拒绝越权和重复副作用；显式区分业务数据提交与非原子的图检查点。

## Decisions

### 1. 独立工作任务和内部通知

Choice：新增 `WorkTaskBatch`、`WorkTaskDraftVersion`、`WorkTask`、`WorkTaskEvent`、`WorkTaskNotification`。工作台路由 `/work-tasks/:id?`，API `/api/work-tasks`；流程投影 scene=work_task。负责人通过现有 `get_user_context(user_id)` 校验，不新增组织目录。创建人与负责人为参与人，来源正文始终单独校验；来源权失效时不返回快照正文，并阻止涉及该来源的新命令。

Rationale：流程任务与有截止日期的业务任务生命周期不同，避免让现有 tasks API 承担两种语义。内部通知允许本阶段验证调度，无需授权外部发送。

Alternatives：直接改 AgentThread 作为业务任务会混淆状态；扩展 OAAdapter 任务写能力目前缺少真实接口，不采用。

批次状态 `CREATED/DRAFT_READY/PAUSED/CONFIRMED/REJECTED`；工作任务状态按 T3。候选唯一键为 tenant+source_type+source_id+source_version+candidate_id；一次确认批次原子创建所选候选。负责人/日期再分派写 event 并使用新 expected_version 和风险确认；通知唯一键包含 task_id+deadline_version+stage+recipient_id。

### 2. 固定指标注册表与独立只读会话

Choice：`report_metrics.py` 登记三个指标，`report_query.py` 对登记计划构建 SQLAlchemy SELECT，使用独立 PostgreSQL REPEATABLE READ READ ONLY 事务且设置 statement_timeout。仅支持日粒度；周/月模板只预置日期范围，不提供周/月聚合。`ReportRecord/ReportVersion` 同在 `report_record.py`，保存计划、批准、快照、摘要和本地发布版本；查询批准先提交，再执行只读查询，并通过写会话保存结果。

Rationale：模型生成 SQL 不适合本阶段的数据边界；数据读取与报告元数据写入要在不同事务内，不能以只读会话承载发布。

Alternatives：通用 BI 连接器和任意 SQL 分析器需要外部数据源和权限评审，不在首批范围。

范围指纹包含租户、当前角色、用户、部门和可见资源范围。固定当前区间和紧邻等长前区间，日期输入按 Asia/Shanghai 归一到 UTC，统计区间为 [start,end)。三个指标均按创建时间入区间，状态分布取查询时状态；审批的不同版本分别计数，并非按完成时间仅统计终态。任务指标去重 creator/assignee 的并集。差异规则使用数量差及相对变化，前期为零不计算比例。模型及人工摘要只接受定性文字，数字仅在工具快照表和图表显示；任何 Unicode 数字或无效指标引用均拒绝。历史读取核对当前权限范围，范围变化要求重建报表。

### 3. 可验证合同原文和四节点 LangGraph

Choice：新增 `ContractRecord/ContractSource/ContractReviewVersion`，规则注册表初版随代码版本化；TXT/PDF 解析复用现有文档文件设施与 pypdf。纯文本按段落和偏移定位，PDF 同时保留 page 和段落。上传文件沿用扫描门，扫描未配置不能绕过 PENDING。独立 contract StateGraph 包含 extract_clauses/check_rules/analyze_risks/summarize；规则检查确定性执行，模型只做结构化提取与建议。

Rationale：证据验证与规则等级不能由自由文本建议决定。LangGraph 保留四个主节点；长文档风险分析节点内部使用 DeepAgents 进行计划和分块多步分析，验证后启用。

Alternatives：OCR/法务知识库实时引用首批不启用。DeepAgents 只开放当前合同的分块读取与计划工具，禁止网络、执行、跨资源文件和业务写入；限制模型调用、递归、读取次数与总超时。依赖或工具输出异常必须暂停，不静默伪装成功。法务规则治理及法律适用性需真实业务评审。

合同报告状态 `CREATED/PROCESSING/DRAFT_READY/PAUSED/CONFIRMED/REJECTED`；指定复核人的身份和角色在每次读取/动作时刷新。不存在的引用、越界偏移和不匹配引文均为模型输出失败。缺失条款用被审查文档范围描述而非伪造引文。

### 4. 共享图设施与业务事务分离

Choice：三个场景各自构建 StateGraph；主图仅增加明确 scene 注册/入口，不允许意图分类将已有业务转为 P3 写操作。专用服务执行授权、版本锁、幂等、决定和事务；图只生成候选/计划/风险，不直接写最终业务。检查点保存运行标识与已验证节点状态，不作为人工确认或外部副作用证据。

Rationale：PostgreSQL 图检查点与 SQLAlchemy 业务提交不共享事务；幂等决定账本是业务提交权威。重启时先查命令结果，禁止依照旧 checkpoint 再次创建业务任务。

Alternatives：将 ORM session 塞进图状态不能可靠序列化；让图节点提交最终业务会增加双写与重放风险，不采用。

通用 thread/messages/interrupt/tasks handoff/retry 路由须拒绝绕过 P3 命令。审计只保存身份、状态、版本、hash 和 trace，不记录原合同和敏感来源正文。公共摘要仅展示有权查看的元数据；完整 DTO 和命令重放都重新检查业务 ACL。

### 5. 数据迁移、UI 与测试隔离

Choice：迁移 0019 工作任务、0020 报表、0021 合同和 0022 提醒扫描公平轮转均为增量表/索引，迁移测试显式创建临时 schema。0022 持久化 notification_scan_at，避免不可用的早期任务长期占用扫描窗口。Vue 工作台沿用现有列表/编辑/历史模式、Element Plus 组件和已有图标。所有动作提供 loading/error/empty/terminal 状态、未保存导航保护、稳定请求键、过期响应丢弃和清晰证据回链。

Rationale：减少框架和 UI 变化，用真实 API 桌面/移动浏览器验证行为。数据测试只使用三个 URL 一致的独立 `_test` 数据库；P2 预览使用同一测试库时必须先停预览后做 reset 测试，测试结束再恢复。

Alternatives：重建数据库或覆盖现有业务迁移不可接受；只用拦截 API 的浏览器测试不能证明数据库状态和权限路径。

## Interfaces

| API | 输入/输出 | 决定边界 |
| --- | --- | --- |
| POST /api/work-tasks/batches | WorkTaskSourceInput -> WorkTaskBatchResponse | 只创建候选批次 |
| POST /api/work-tasks/batches/{id}/extract | VersionedCommand -> WorkTaskBatchResponse | 提取/重试，不创建任务 |
| PATCH /api/work-tasks/batches/{id}/draft | WorkTaskDraftUpdate -> WorkTaskBatchResponse | 追加保存版本 |
| POST /api/work-tasks/batches/{id}/decisions | WorkTaskDecision -> WorkTaskBatchResponse | 确认后原子创建所选任务 |
| GET /api/work-tasks、GET /api/work-tasks/{id} | WorkTaskPage、WorkTaskResponse | 创建人/负责人范围 |
| PATCH /api/work-tasks/{id}、POST /api/work-tasks/{id}/commands | WorkTaskUpdate、WorkTaskCommand -> WorkTaskResponse | 版本锁、角色与状态机 |
| GET /api/work-tasks/notifications、POST /api/work-tasks/notifications/{id}/read | WorkTaskNotificationPage、VersionedCommand | 接收人范围 |
| GET /api/reports/metrics、POST /api/reports | MetricDefinition[]、ReportInput -> ReportResponse | 登记指标、保存待批准计划 |
| POST /api/reports/{id}/approve-plan | ReportPlanApproval -> ReportResponse | 人工确认登记计划后查询/生成 |
| POST /api/reports/{id}/retry | ReportCommand -> ReportResponse | 受控恢复；模型失败复用合法快照 |
| PATCH /api/reports/{id}/draft | ReportDraftUpdate -> ReportResponse | 定性摘要编辑，追加版本 |
| POST /api/reports/{id}/publish | ReportPublication -> ReportResponse | 确认口径与候选原因，平台发布 |
| GET /api/reports、GET /api/reports/{id}、GET /api/reports/{id}/versions | ReportPage、ReportResponse、ReportVersion[] | 当前范围指纹一致 |
| POST /api/contracts、POST /api/contracts/uploads | ContractInput、multipart -> ContractResponse | 创建私有原文版本，扫描门 |
| POST /api/contracts/{id}/commands | ContractCommand -> ContractResponse | review/retry/save/confirm/reject |
| GET /api/contracts、GET /api/contracts/{id}、GET /api/contracts/{id}/versions | ContractPage、ContractResponse、ContractReviewVersion[] | 创建人/指定复核人 ACL |
| GET /api/contracts/{id}/sources/{source_id} | ContractSourceResponse | 私有证据定位；不提供公开文件 URL |

VersionedCommand 统一包含 idempotency_key 与 expected_version；创建命令包含 idempotency_key。含副作用的结果重放先做当前身份/资源检查；同键不同 payload 返回冲突。列表总数与分页使用相同 ACL。静态路径注册先于 /{id} 路径。

## Risks And Trade-Offs

- 本地审批/工单指标不是企业 BI；缺真实数据时不能宣称生产报表正确。
- 合成合同样本证明证据与流程行为，不证明法律判断质量；真实复核人角色映射仍需组织确认。
- 独立评测、成本上限、当前权限过滤必须有运行证据，文档设计不等于进入条件已验收。
- 原文及快照私有存储须检查 checkpoint、审计和通用任务入口，避免旁路泄露。
- 提醒调度独立子步骤捕获失败，不能影响现有审批催办；禁用 P3 不修改 P1/P2 开关。
