# P2 会议文本智能体设计

## Context

当前平台以 AgentThread 作为会话和 LangGraph thread_id 主锚点，已经具备统一认证、租户隔离、幂等命令、HITL 中断、PostgreSQL Checkpoint、审计事件、运行 Span 和降级控制。P2 第一批只做会议文本，不依赖真实 OA 或外部任务系统，因此必须在复用平台底座的同时明确禁止外部写入。

主要参与者是会议发起人/参会人、管理员和运维人员。会议内容可能包含敏感的人事、业务和客户信息，原文不应进入普通日志或审计摘要；草稿结果需要可编辑、可追溯、可恢复。

## Goals

- 将会议文本可靠地转换为可审阅的纪要、决策和待办草稿。
- 保留原文片段与结果项之间的可追溯关系。
- 复用 P1 的权限、HITL、幂等、Checkpoint、审计和观测机制。
- 让编辑、确认、拒绝和重新生成都具有明确状态与可恢复性。
- 在真实 OA 未接入时保证确认操作没有外部副作用。

## Non-Goals

- 音频/视频转写和说话人识别。
- 外部 OA、任务、日历或邮件系统写入。
- 文档起草和邮件分类子图。
- 企业 SSO、组织主数据和通用流程引擎。

## Decisions

### Decision 1: 复用 AgentThread，新增 meeting 场景

**Choice:** 使用现有 AgentThread，scene 取 meeting，business_id 指向稳定 meeting_id；会议领域数据通过独立表保存。

**Rationale:** 复用既有会话查询、消息、权限、Checkpointer、任务投影和运行追踪，避免再造一套会话主表。

**Alternatives considered:** 单独建立 MeetingThread 主表会减少 scene 分支，但会重复认证、恢复和任务列表逻辑；本批不采用。

### Decision 2: 原文、片段和草稿版本分离

**Choice:** 使用 MeetingRecord 保存元数据，MeetingSource 保存原始文本引用和哈希，MeetingSegment 保存有序来源片段，MeetingDraftVersion 保存不可覆盖的结构化草稿版本。

**Rationale:** 原文和生成结果生命周期不同；版本分离可以支持编辑差异、重新生成、审计和恢复，并避免覆盖用户已经确认的版本。

**Alternatives considered:** 将所有内容放进 AgentThread JSON 会实现更快，但查询、授权、版本比较和数据迁移不可控，不采用。

### Decision 3: 结构化草稿使用显式 DTO 和服务端校验

**Choice:** 纪要、议题、决策和待办使用明确的 Pydantic DTO；模型或规则输出先通过 schema 校验，再写入草稿版本。

**Rationale:** 内容生产结果需要稳定的前端契约和字段级编辑；显式校验可阻止模型输出任意字段、伪造确定的负责人或截止时间。

**Alternatives considered:** 直接保存任意 JSON 并由前端解释，短期灵活但难以保证兼容性和安全边界，不采用。

### Decision 4: 会议子图独立接入 SuperAgent

**Choice:** 新增 meeting_graph.py，并在 SuperAgent 根据 scene=meeting 路由；解析、生成、等待审阅和恢复节点均使用现有 GraphRuntime。

**Rationale:** 子图隔离便于降级、测试和未来独立关闭，不影响 P1 请假、FAQ 和工单流程。

**Alternatives considered:** 将会议逻辑塞入 FAQ 或 ticket graph 会减少文件数量，但会混淆业务状态和审计动作，不采用。

### Decision 5: 人工确认只产生平台内确认记录

**Choice:** 会议确认使用独立 meeting decision 命令和幂等记录；本批不注册任务、日历、邮件或 OA 写工具。

**Rationale:** 符合 P2 第一批无真实 OA 依赖的范围，也能验证高影响操作前的人工门和幂等行为。

**Alternatives considered:** 先写 Mock 任务/日历再切换真实 OA，会掩盖外部契约和对账风险，延后到后续批次。

### Decision 6: 敏感内容分层记录

**Choice:** 数据库保存受权限保护的原文和草稿；审计、运行 Span 和普通错误日志只保存脱敏摘要、哈希、数量和定位信息，不保存完整会议文本。

**Rationale:** 会议内容可能含敏感信息，运维可观测性不应扩大内容暴露面。

**Alternatives considered:** 审计保存完整输入便于排查，但违反最小暴露原则，不采用。

## Interfaces

### HTTP API

- POST /api/meetings：创建会议文本任务。
- GET /api/meetings：按当前用户/租户列出可见会议任务。
- GET /api/meetings/{meeting_id}：读取会议状态、当前草稿和可用操作。
- POST /api/meetings/{meeting_id}/generate：启动或恢复草稿生成。
- PATCH /api/meetings/{meeting_id}/draft：保存可编辑草稿版本。
- POST /api/meetings/{meeting_id}/decisions：提交 confirm、reject 或 regenerate 决定。
- POST /api/meetings/{meeting_id}/retry：重试可恢复暂停任务。

所有写命令 MUST 带幂等键或由服务端生成稳定命令键，并返回 trace_id、meeting_id、状态和下一步动作。

### Domain Types

- MeetingRecord：会议元数据、租户、所有者、状态和当前版本。
- MeetingSource：文本哈希、来源类型和安全存储引用。
- MeetingSegment：顺序、字符范围、文本摘要和原文定位。
- MeetingDraftVersion：摘要、议题、决策、待办、来源引用和版本状态。
- MeetingDecision：操作者、动作、评论、幂等键和结果快照。
- MeetingCapabilities：当前平台能力，明确 external_writes=false。

## State Model

CREATED -> PROCESSING -> DRAFT_READY -> REVIEWING
DRAFT_READY -> PAUSED
REVIEWING -> CONFIRMED
REVIEWING -> REJECTED
REVIEWING -> DRAFT_READY（重新生成）
PAUSED -> PROCESSING（安全重试）

编辑会创建新的草稿版本并回到 REVIEWING；确认或拒绝后，原版本不可覆盖。任何状态迁移都由服务端校验，不由前端直接决定。

## Failure And Recovery

- 输入校验失败：返回结构化 4xx，不创建处理版本。
- 解析/生成失败：保存错误码、trace_id 和 checkpoint，任务进入 PAUSED。
- 重复命令：由统一幂等服务回放首次结果。
- 服务重启：通过 AgentThread 的 LangGraph checkpoint 恢复最新节点和草稿版本。
- 外部写入：本批不允许注册或调用；若未来扩展，必须单独增加能力声明、确认命令和对账接口。

## Risks And Trade-Offs

- **模型输出不稳定：** 通过结构化 DTO、来源引用和缺失字段保留不确定性降低风险；代价是部分文本需要人工补全。
- **会议原文敏感：** 通过对象/数据库权限和审计脱敏控制；代价是排查问题时需要依赖哈希和 trace 关联。
- **长文本处理耗时：** 采用分段和 Checkpoint；代价是生成结果可能需要多次状态刷新。
- **P1 与 P2 共用 AgentThread：** 可复用底座但会增加 scene 分支复杂度；通过独立 meeting graph、服务和测试边界控制。
- **暂不接外部写入：** 降低上线风险但本批只能验证平台内确认闭环；后续 OA/任务写入必须另行评审。

## Verification Strategy

- 单元：分段、结构化抽取、状态迁移、敏感摘要、权限判断。
- API：创建/读取/编辑/确认/拒绝/重生成、幂等冲突、跨租户隔离、暂停恢复。
- Graph：正常生成、模型失败、重启恢复、重复恢复不重复生成。
- Frontend：会议输入、草稿编辑、确认门、错误状态和管理员审计入口。
- Regression：P1 全量后端、前端组件、构建和现有角色 E2E 必须保持通过。
