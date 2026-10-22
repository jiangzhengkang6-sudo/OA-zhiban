# M3 技术设计

日期：2026-10-19。已随执行契约获用户批准；实施与验收状态见 execution-plan.md。行为以 [规格](specs/formal-business.md) 为准。

## Context

M2 数据库基线为 0024。OAWorkflowInstance.leave_version_id 非空，审批、转交和定时器都直接读取 OALeaveVersion；不能只修改 scene 字段就支持报销。OAWorkflowOutbox 只有 PENDING/SENT/FAILED。BuiltinLeaveProvider 是旧预检包装，不能充当 M2 权威；ProviderBundle 当前在 builtin 模式主动拒绝。图节点/工具调用同步 get_adapter，协议缺少 actor/session/version。正式知识、策略、审计、运行管理和旧业务入口仍被 503 保护。

TicketRecord 虽然持久化，但创建调用外部适配器，旧读权限依赖 cs/admin 角色；合并目标未参与 payload_hash。OAUser 无邮箱，不能直接假定有可外发地址。P2/P3 已有最新身份和 resource_clause，但知识回退、报表旧来源及相关预览/导出仍需逐入口审查。

继续使用 Vue、FastAPI、SQLAlchemy、PostgreSQL、LangGraph 单体；不替换已有图框架或引入新的通用工作流平台。无 ssf 配套工具、Git 尚无 HEAD，拟采用与 M2 相同的人工执行记录和当前实施者串行复核；必须重新取得本阶段批准，不制造工具收据或独立审查事实。

## Goals

AI 可关闭的确定性报销/工单/通知，完整内桥回接，统一正式身份和可重放命令；保住 M2 日期、余额、并发和私有附件语义。明确区分业务提交、图完成、渠道受理三类事实。所有验证在专用环境、无付费调用及实际外发下完成。

## Decisions

### D1 异步网关及可信上下文

Choice：新增 OAGateway 异步协议和 BuiltinOAGateway；每次以 BridgeContext(actor: CurrentUser, session: AsyncSession, trace_id: str, confirmation_id: str | None) 构造。builtin 直接调用正式领域服务，不发回环 HTTP，不使用 asyncio.run 或另起独立事务。旧 Mock/real 由 LegacyOAGateway 将同步网络调用放入工作线程，并保持显式配置边界；写前最新授权和本地结果记录仍由异步调用者负责。

Rationale：网关共享提交前身份校验和领域事务，避免同步兼容包装破坏锁和提交边界。Capabilities 的静态声明只表示实现，readiness 再报告依赖是否可用；SMTP 未配置不会伪造邮件能力。

Alternatives：继续给同步 adapter 塞全局 actor/session、同步函数中跑事件循环，均拒绝。get_adapter 的 builtin 旧调用保持明确拒绝，调用点清单逐项迁移；验收不留隐式同步访问。OA_PROVIDER=builtin 要求 builtin 身份，不能混接 Mock 用户。

### D2 共用引擎、有类型的业务关联

Choice：0025 增加 oa_reimbursement、oa_reimbursement_version、oa_reimbursement_attachment。OAWorkflowInstance 增加 scene 和可空 reimbursement_version_id，leave_version_id 改可空；CHECK 要求 leave 仅关联 leave_version_id，reimbursement 仅关联 reimbursement_version_id，两个关联各自租户复合外键和唯一约束。原行仅标记 scene=leave，关联值和业务内容不变。

新增 OAWorkflowSubject 包含 scene、object_id、version_id、owner_id、department_id、submission_version、state、fields、attachment_manifest。通过受限 scene 分派读取正式对象，共用节点/席位推进；余额预留/结算仅在 leave 钩子执行。保留 M2 原服务签名，通过共用引擎调用；在同一批完成审批、转交、定时器和对账的所有 join 更新，不能留下半套报销支持。

Rationale：复用已经验证的审批并发机制，业务专属约束仍在各自服务。Alternatives：复制整套节点、席位、转交引擎会使修复分叉；以无外键的 business_type/business_id 关联无法保证完整性，均不采用。

### D3 报销字段和金额

Choice：固定基础字段 purpose、expense_date、category、amount、currency、attachment_ids；currency 只接受 CNY。金额 API 接受普通十进制字符串，拒绝指数、空白、符号及多余小数位；Decimal 校验后转整数分，数据库 BigInteger 与 1..99999999999 CHECK。响应固定两位小数。流程 amount 条件在发布时转整数分，仅使用允许比较操作，无 eval。

scene 对应受限表单字段字典，表单/规则/流程版本及哈希固定。金额、日期、用途和发票等关键字段在审不允许直接覆盖，沿用退回重提。至少一张通过扫描的发票附件，复用内容校验、扫描及存储完整性函数；新附件表绑定报销，禁止与请假串用。发票真实性和财务支付不在本阶段。

Alternatives：浮点金额和提交时自动四舍五入不可接受；自动 OCR/税务查验会引入未授权费用和依赖，不引入。

### D4 正式工单独立权威

Choice：0026 新建 oa_ticket、oa_ticket_assignment_rule、oa_ticket_feedback，复用 M2 命令/事件底座。保留旧 TicketRecord 及 API 的 Mock/real 行为；builtin 路由、工具和报表明确走新服务，不能从找不到正式记录退回旧数据。人工创建无需 AgentThread；AI 草稿通过正式确认后调用同一命令。

字段含 owner/department、revision、状态、队列、有效处理人和固定分派规则版本；状态限定 OPEN/IN_PROGRESS/RESOLVED/CLOSED。无有效规则为待领取；领取/转派需要 ticket_handle，分派配置需要 ticket_admin，创建和本人反馈需要 ticket。部门权限仍需最新成员范围；跨部门或无效处理人拒绝，缺处理人时保留待领取，不能自动授予管理员办理权。

合并仅本人 OPEN/IN_PROGRESS 目标，经重复候选选择、目标 revision 和确认；同键载荷含目标、源内容及版本。合并事件和原命令结果持久化，不依赖目标当前状态推断历史结果。没有规则或授权客服的负面反馈保持 OPEN/待领取并提示人工，不落入未隔离的旧 HumanQueueItem。

Alternatives：给旧表加 builtin 标志会使遗漏筛选暴露 Mock 历史；独立正式表能建立清楚的租户外键，故选择独立权威。

### D5 通知意图与渠道尝试

Choice：0027 新建 oa_notification、oa_notification_delivery、oa_notification_attempt、oa_user_contact；OAWorkflowOutbox 继续作为 M2 事件来源。桥接器按源 outbox ID 唯一创建正式通知，再分别生成 inbox/smtp 渠道任务。旧 SENT 只表示事件已持久化交接到正式队列，不能当 SMTP 送达；旧 PENDING 业务通知可接入，过期提醒按当前节点取消，不整体重发历史。

站内记录以 (tenant,source,recipient) 唯一、已读时间幂等。渠道任务使用 SKIP LOCKED、租约及 attempt token 领取，事务提交后执行外部 IO，再凭 token 记录结果；过期 PROCESSING 若有外部执行可能则 UNKNOWN，禁止直接重投。明确暂时未受理失败最多 3 次，间隔 1/5/30 分钟；永久失败停止。UNKNOWN 仅能由通知管理权限人员人工核对、记录备注并显式重试，提示重复风险；稳定 Message-ID 不被当作 SMTP 去重保证。兼容 NotificationResult.delivered 仅对已成功入箱的站内信为 true，SMTP ACCEPTED 仍为 false，并在 payload 明示渠道受理状态，不宣称用户收到或阅读邮件。

收件人配置属本账号或授权部门管理；变更产生审计并使待发任务重新解析地址，队列/普通响应不存可公开邮箱。投递前、入箱和读取再次验证来源及收件人权限；提醒检查节点/席位/终态。SMTP 只发简短提示和配置的应用入口，不含业务明细。业务提交不等待外部投递，也不因投递失败回滚。

Alternatives：业务事务内 SMTP、声称 exactly-once、超时直接重发均拒绝。测试只用本机捕获 SMTP 服务及故障注入，不操作真实邮箱。

### D6 确认和业务结果恢复

Choice：0026 同时增加 oa_bridge_confirmation、oa_bridge_result。确认记录绑定 actor/tenant/thread/action/object/node revision/payload hash，10 分钟有效、单次消费；与领域写入和结果映射同事务。有效确认可产生一次领域动作，已消费确认的同键重放经最新授权后读取结果；旧版本/异载荷必须重新确认。BridgeResult 记录 core method、原 key、actor、目标及版本、正式 operation ID/结果，不存私密正文。

核心 13 项计数按 [C01-C13](specs/formal-business.md)；A01/A02 单独测试。新增外桥工单结果读接口并保持既有路径/DTO兼容；目标 real 服务未支持时明确报告，不新增模拟成功。未知写结果只读对账、必要时转人工，图 checkpoint 不充当写入凭证。AI 请求的 route/user_id 只作输入提示，实际操作者和路线由服务端裁决。

### D7 逐入口开放正式权限

Choice：新增 reimbursement、ticket、ticket_handle、ticket_admin、notification、notification_admin、knowledge、policy、audit、operations 资源，不修改原角色的既有授权。notification self 仅本人，管理资源只准 department；知识发布与策略管理只准部门 write，普通问答仅使用可读取已发布来源。操作管理不因部门权限获得整个系统的敏感配置。审计列表、详情和导出依据业务对象权限和部门边界过滤。

对 thread/task/interrupt/support 按实际功能建立入口与工具清单；builtin 只开放已隔离路径，旧 support 不直接获得泛客服角色。知识按 tenant、owner/department、发布版本在向量/关键词查询前过滤，生成/引用前复核，禁止旧 chunk fallback。P2/P3 的已有 business_boundary/resource_clause 延续；所有来源读取、任务生成、报表聚合、快照、下载/导出均复核来源权限，报表只从正式表读取 builtin 数据。

旧 AgentPolicy 和 AuditEvent 不含可依赖的租户权属，不用于正式管理权威。0028 增加 oa_knowledge_binding、oa_agent_policy、oa_agent_policy_version、oa_business_audit：知识 binding 仅绑定正式导入且属于该租户的新 source，保存 owner/department 与版本访问规则；不自动绑定旧资料。策略固定租户/部门，用户范围须为当前有效成员，无可写 global 范围；版本发布后固定，未配置使用代码内保守默认值。正式 AI/管理审计写入有明确租户、资源、对象和部门的记录；领域成功审计继续与 OAWorkflowEvent 同事务并增加 trace/版本/差异信息，审计页面按来源权限联合读取。原审计没有可证明权属的行不向正式账号展示。绑定 source 的外键和租户一致性在迁移/服务中同时保证。

Alternatives：移除 deps 的整段 503、靠前端菜单隐藏、仅生成后过滤都不能满足范围约束。模型关闭时正式人工路由/调度/通知仍工作；知识、报表生成等 AI 动作明确不可用但允许手工业务。

### D8 迁移、执行和预览

Choice：0025 共用引擎/报销及领域事件追踪字段、0026 工单/确认/对账、0027 通知渠道、0028 正式知识绑定/策略/审计，顺序增量升级；逐级测试空库、0024 含数据升级、重复 upgrade 和约束。0024 以后的正式数据迁移不得通过降级清除，沿用破坏性 downgrade 拒绝原则，不虚构备份恢复验收。

专用两个 M3 库须先明确批准；三种 URL 显式设置并通过 safety 校验。专用预览随机账号，Mock LLM/embedding，独立配置与文件存储。先取得契约/人工串行替代批准，按 B1-B7 每批测试和实施者复核通过才继续；联合数据库测试串行。前端沿用 Element Plus 和现有中文工作台样式，新页面完成后桌面/390px 浏览器验证。

## Risks And Trade-Offs

| 风险 | 处理及验收 |
| --- | --- |
| 共用引擎改动影响请假 | B1 先跑 M2 审批/余额/并发/转交/调度回归，未通过不进入报销业务 |
| 旧图或工具绕过正式网关 | 建立调用清单，扫描 get_adapter 和直接表读取，逐项权限/恢复测试 |
| 邮件未知结果难以自动判断 | UNKNOWN 保留人工核对，不承诺一次且仅一次；故障注入覆盖受理后断连 |
| 管理模块扩大成全局权限 | 正式范围谓词、直达/导出/部门换岗测试，未隔离能力保留拒绝 |
| 测试和预览误操作原库 | 批准库名白名单、三地址核验、拒绝随机额外建库、不并行重置 |
| 单人实施复核不能替代独立审查 | 明确标为实施者复核，保留证据；生产与 M4另行评审 |

无未定架构选项。若实现必须改变金额单位、业务外键结构、确认语义、批次边界或授权/数据库范围，先更新契约再确认；普通内部函数拆分、fixture 和错误修复在契约内自主处理。
