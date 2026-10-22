# M2 设计

日期：2026-10-18。状态：用户已批准，实施中。需求见 [行为规格](specs/manual-workflow.md)。

## Context

代码基线为迁移 0023。旧 `leave_application_service` 在预检和路由中读取 Provider；`ApprovalNode` 有每实例一个 ACTIVE 节点的限制，且一个节点仅一个 approver。builtin 身份在 `api/deps.py` 拦截旧 leaves/approvals/interrupts，组织资源白名单尚无正式请假资源；应用启动无条件初始化 LangGraph。M1 身份服务提供租户锁、当前权限和提交前身份校验，可作为正式业务的边界。

参与人：申请人、有效审批人、抄送人、具备部门业务管理权限的管理员。系统管理员身份本身不授予批准权。现有真实配置、原数据库、旧 Mock 预览及尚无 HEAD 的工作区都必须保持。

## Goals

AI 关闭也能完成确定性的请假闭环；多进程并发下状态和额度一致；模板变化不改历史；禁用/调岗和转交即时约束权限。新人工领域服务将成为 M3 内桥的调用目标，不额外建立第二套流程执行器。

## Decisions

### D1 独立正式业务边界

Choice：新增 `/api/oa/leaves`、`/api/oa/approvals`、`/api/oa/workflows`、`/api/oa/balances`、`/api/oa/administration`，全部仅接受 builtin 身份。每个路由与领域服务显式授权，不给 `oa` 前缀通用放行。旧接口继续使用原逻辑；M3 再让内桥调用这些领域服务。

Rationale：旧表绑定 AgentThread 和 Mock 权威，不适合直接放宽权限后复用。新流程不调用 LLM、嵌入、MockAdapter 或图 invoke。

Alternatives considered：扩张旧审批表会改变旧 Provider 和图协议；现在接完整内桥会越过 M3 范围。

### D2 数据结构与版本

Choice：0024 仅增加以下 13 张表，不回填/改写旧业务：

| 表 | 责任与主要约束 |
| --- | --- |
| oa_workflow_definition | 租户/部门/场景/编码、草稿定义、修订、当前发布版本 |
| oa_workflow_version | 不可变发布版本；固定 form_version/rule_version、schema/规则/流程 JSON、各哈希；租户/定义/版本唯一 |
| oa_leave | 申请人、业务号、可编辑草稿、draft_revision、submission_version、业务状态、archived_at；业务号租户内唯一 |
| oa_leave_version | 单据/提交版本唯一；不可变标准字段、附件清单、预检、三类版本、差异摘要 |
| oa_workflow_instance | 每提交版本一个实例；固定 route_snapshot、route_revision、state、lock_version |
| oa_workflow_node | 实例/顺序唯一；单签/会签/或签/抄送类型、状态、修订、到期及催办标记 |
| oa_workflow_seat | 节点/席位唯一；原始人、有效人、资格约束快照、状态、代理/转交/升级标记；有效席位按人员去重 |
| oa_workflow_operation | 命令种类、目标、目标版本、操作编号、操作者、规范载荷哈希、结果；数据库唯一作用域 |
| oa_workflow_event | 租户化业务审计；操作者、命令、追踪、对象/版本、脱敏差异、理由、时间；追加不改历史 |
| oa_workflow_outbox | 租户/事件/收件人/用途唯一；关联最小业务 ID，PENDING 状态，无 M2 外发 |
| oa_leave_balance | 租户/用户/假种/年度唯一；整数 total/used/reserved，非负及不超额度 CHECK |
| oa_leave_ledger | 初始化/调整/占用/扣减/释放台账；提交版本/年度/操作类别去重，记录前后值 |
| oa_leave_attachment | 租户/单据归属、私有存储引用、真实 MIME/大小/哈希、扫描结果；提交清单引用后不可覆盖 |

所有子表具有 tenant_id，父子及用户/部门引用使用同租户复合外键和约束，禁止仅凭全局 UUID 关联。旧 AuditEvent 无租户且其查询仍未开放；M2 用带租户业务事件承载审批审计，M1 生命周期审计保持。

草稿 JSON 可变但带乐观修订；创建时显式选择同部门的 workflow_definition_id，提交只能使用该定义当前已发布版本，禁止由客户端指定历史/未发布版本。发布操作在锁内递增流程版本，表单或规则哈希变化时分别递增对应逻辑版本，旧发布行不可更新。提交材料及发布配置不可变。管理员改路线只生成 route_revision 和历史事件，不改提交快照或已完成决定。无需新增独立流程/表单/规则执行服务，三类逻辑版本在同一发布包中固定并可追踪。

Alternatives considered：共用未租户化审计查询会扩大 M1 已关闭的管理面；仅存当前表单不能满足重提和历史材料授权。

### D3 有限流程 DSL

Choice：定义 `schema_version=1, scene=leave, entry_id, nodes[]`。节点 kind 为 approval/cc/branch/end；审批 mode 为 single/all/any，selector 为 manager/users/role；角色选择限定申请人部门，上级层数为 1–10，指定人可显式跨部门。节点 `next_id` 及 branch 的 cases/default_next_id 只允许构成前向无环图。分支支持 eq/ne/lt/le/gt/ge/in；值按表单声明类型校验，禁止脚本、eval、网络和任意函数。发布验证所有路径终止、有审批节点、单签能产生单席。

表单声明类型、必填、长度、假种字典；请假字段固定为 leave_type/start_date/end_date/reason/attachment_ids。派生 days 为整数；请假未声明 amount，引用金额分支会拒绝。编译器的金额类型用 Decimal 且仅在纯单元测试中验证，为 M3 留类型契约，不接报销表单。规则包声明所需材料、日历日计数、每假种额度约束和超时时间。不得在已有模板下接受未知字段。

提交时解析条件和人员并保存固定路线；空人/自审/不合格人产生 PAUSED 实例及管理员待发送事件，不通过。新发布版本仅用于新提交轮次。

Alternatives considered：通用 BPMN、任意表达式和拖拽编辑器增加不必要执行面；M2 使用受限 JSON 存储及结构化配置界面。

### D4 日期和余额

Choice：正式字段使用日历日期，不接受模糊时间或半天。含首尾整天数，同日一天，跨年切分到各年度账户。所有配置假种使用显式有限额度；管理员按用户/假种/年度初始化和调整，提供原因、expected_revision、operation_id，不自动导入 Mock 余额。

重叠采用闭区间：start_date <= other.end_date 且 end_date >= other.start_date；在办、暂停、已通过参加检测，驳回和取消不参加。提交前串行锁定申请人，覆盖不同假种/年度，避免只锁余额造成重叠穿透。额度足够且材料有效才创建提交；若仅人员路线异常，提交为 PAUSED 并保留占用，申请人可撤回释放。通过后不支持销假返还，另立后续需求。

### D5 锁顺序、幂等和事务

Choice：短事务统一锁序为 M1 租户身份锁 -> 租户/申请人事务锁 -> 单据 -> 实例 -> 节点/席位 -> 按年度/假种排序的余额。管理配置变更同用租户锁；同事务提交前保留 M1 身份和会话复核，并复核受影响人员资格。扫描/文件解析在锁外执行，回到锁内校验草稿修订、字节哈希和扫描结果。

提交键为 `(tenant, submit, leave_id, requested_submission_version, operation_id)`；决定键为 `(tenant, decide, instance_id, node_id, operation_id)`，记录 actor_id 和规范化载荷摘要。其他命令同样有命令/目标/operation_id 作用域。载荷拒绝未知字段；日期、数组及 Decimal 规范化后哈希，不含会变化的服务时间。先当前授权，再幂等返回；唯一键竞争后重新读取已提交结果。同键载荷/操作者不符拒绝，失败事务不留下假成功。

每次修改使用 expected_revision；同一命令重放优先识别已保存结果。不同操作编号竞争时，锁内按节点/实例当前状态裁决；后到响应仅携带当前可见状态，不新增决定或结算。发生转交导致读取资格消失时返回权限拒绝，不能以幂等缓存泄露旧材料。

业务、席位、台账、操作结果、审计和 outbox 在同一个会话事务提交。无服务内部提前 commit；API 负责最终提交。M2 审计不记材料原文，业务事件留字段名/必要脱敏差异和关联版本。文件存储不宣称数据库式原子性：上传失败/回滚产生的无引用字节由独立忽略目录清理；已提交引用文件不删除。

Rationale：数据库锁和唯一约束跨进程有效；与 M1 组织更新共用租户锁，避免禁用/调岗竞态。代价是同租户写入较保守，适合当前部门规模；不在扫描或模型调用期间占锁。

### D6 状态与决定

Choice：业务状态 DRAFT/IN_REVIEW/PAUSED/APPROVED/REJECTED/CANCELLED；archived_at 独立，display_status 可显示 ARCHIVED 但保留 outcome。非归档草稿、驳回和取消可由申请人编辑；在办/暂停先撤回才能改关键字段。归档只允许终态。

single、all、any 仅在当前节点接受有效决定；any 首次批准/驳回使其他席位失效，all 任一驳回终止，all 全批准才推进。补充编辑仅允许 approval_note，不修改申请表；要求关键变更使用 return_for_correction，保留结构化原因并按驳回释放，申请人确认后产生新提交版本。禁止终态继续决定。

### D7 授权与交接

Choice：资源为 leave、approval、workflow、leave_balance、workflow_admin，各分 read/write；普通成员可分配 leave self read/write，审批人需要 approval self read/write。发布、额度调整、转交各需对应管理资源 department 权限，管理范围必须有有效部门，不因 admin 角色名自动放行。现有角色不自动获得新增敏感权限，管理员通过组织页面显式分配。

| 访问 | 最小范围 |
| --- | --- |
| 我的申请/变更/撤回 | 申请人本人 + leave 对应权限 |
| 部门申请读取 | leave department read + 申请人当前同部门；不因此可审批/代改 |
| 当前节点上下文 | approval read + 当前有效席位；仅该轮材料，不含余额或其他轮次 |
| 已办 | 本人已完成决定的摘要、本人决定与版本标识；不自动取得历史附件原文 |
| 抄送 | 激活时固定收件人 + approval read；最小摘要，材料需单独有效读取权 |
| 决定 | approval write + 当前有效席位 + 当前资格 |
| 流程发布/额度调整/转交恢复 | 对应资源 department write + 当前部门范围；同时读取详情还需最小对应管理读取权限 |

自动解析和正常办理校验同租户、启用、部门/岗位/角色/主管关系满足固定路线约束、当前资源权限、非申请人。配置变化不静默换人；资格变化不产生批准或扣减，后台检测器持有相应权限后暂停并记录异常，读取接口本身不改状态。

管理员逐席代理/转交不创建永久委托关系，不允许链式再委托或重复会签席位。显式替代可以变更原指定人/主管这一选择结果，但接收人仍须启用、具有 approval read/write、非申请人且未占同会签其他席位；接收范围限申请人当前部门，或原发布版本显式 users 候选集中的跨部门人员。不得借转交新增其他跨部门候选。管理员可修订当前及尚未激活节点的未完成席位，不能重写已完成决定；更换有效人需要理由、expected_revision 并增加路线修订，保留原人、资格约束和历史。

M1 的 handoff_pending 是全业务标记。M2 返回 remaining_m2_seats 和 m2_handoff_complete；只完成 M2 待办不能把全业务标记改成 false，待 M3/V2 全范围交接核对后再清除。

### D8 超时和恢复

Choice：新调度器只扫描正式表，在 builtin 模式接入现有 scheduler 循环；AI 关闭时也运行。逐单据取得统一锁后重新确认节点与截止时间，以 `(node, route_revision, seat, kind)` 去重；转交保留原截止时间，显式恢复记录新的截止时间和理由。催办只写事件；每席一次自动升级到当前有效人合格上级，无上级、重复席位、自审或角色不合格则 PAUSED，产生管理员事件。终态持锁复核后不再新增有效提醒。

支持只读对账：提交版本唯一实例、有效节点/席位、占用与台账、终态结算、操作/事件一致性。发现不一致报告并安全暂停相关继续操作，报告不等于自动改账；重试必须复用操作键。恢复使用固定版本及显式路线修订，禁止根据图状态补造批准。

### D9 AI 关闭与界面

Choice：新增 AI_ENABLED（默认 true，测试/预览显式 false）。main 仅在启用时初始化/关闭 LangGraph；图相关入口和工具明确报不可用，保留原检查点。旧 Mock 调度只在 AI 开启且 Mock 身份运行，正式人工调度不依赖该开关。`/auth/config` 增加安全能力标志，前端按身份和权限显示 `/oa/*` 人工页面，智能入口显示可用状态。

界面使用现有 Element Plus；新增我的请假、审批中心（待办/已办/抄送）、申请与节点详情、流程配置（节点/条件结构化编辑）、额度和异常管理。普通页面中文标签，不显示 JSON 输入。允许操作由后端返回，前端防重复只是交互辅助。节点详情与申请人详情分开，防止拿到额外材料。响应处理沿用会话变更防串号机制。

## Risks And Trade-Offs

- 日历整日规则、所有假种显式额度和跨年拆分需要业务负责人在试点前确认；本轮批准仅确定实现规则，不代表真实额度已获确认或已导入。
- 未配置 ClamAV 时需要附件的申请会被阻止；测试可注入明确 CLEAN 的扫描替身，生产不得模拟扫描通过。
- M2 只持久化通知事件，尚无站内消息/SMTP 送达能力；管理员仍通过审批/异常页面办理。
- 仍需 M3 完成 Provider/内桥与其他业务正式化，生产 Mock 门禁保持。M2 完成不等于完整正式 OA 或生产可上线。
- 新迁移成为 head 后旧 M1 预览库需显式升级才可重启。M2 使用新的隔离预览库和端口，保留当前 M1/P3 进程及原库。
- 本机缺少 ssf 工具及配套脚本，仓库无 Git HEAD。执行前需要本轮确认人工计划和审查替代，不伪造机器收据或提交。
