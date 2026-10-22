# P2 会议文本智能体实施任务

## Execution Rules

1. 严格按 M1 → M4 执行；未满足依赖、测试和评审条件不得开始下一批。
2. 每个任务遵循 Red → Red Verify → Green → Green Verify → Refactor。
3. 数据库只通过 Alembic 迁移；不得清空开发库、删除 Docker 数据卷或使用 create_all 模拟升级。
4. API/图测试只能连接名称以 _test 结尾、ENVIRONMENT=test 且显式允许清理的独立测试数据库。
5. 会议确认本批只写平台内记录；不得注册或调用外部 OA、任务、日历和邮件写工具。
6. 每批结束必须保留测试输出、更新功能实测文档或对应 P2 验收记录，并执行 P1 回归。

## File Structure

### Backend

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | backend/app/models/meeting_record.py | 会议任务元数据、租户、所有者和状态 |
| Create | backend/app/models/meeting_source.py | 原文哈希、来源类型和受限存储引用 |
| Create | backend/app/models/meeting_segment.py | 有序文本片段、字符范围和来源定位 |
| Create | backend/app/models/meeting_draft_version.py | 不可覆盖的结构化草稿版本 |
| Create | backend/app/models/meeting_decision.py | 确认、拒绝、重新生成和幂等结果 |
| Create | backend/app/schemas/meeting.py | 输入、片段、草稿、决定和响应 DTO |
| Create | backend/app/services/meeting_parser.py | 文本校验、分段和来源定位 |
| Create | backend/app/services/meeting_service.py | 会议创建、读取、版本、权限和状态迁移 |
| Create | backend/app/graph/meeting_graph.py | 会议解析、草稿生成、暂停和恢复节点 |
| Create | backend/app/api/routers/meetings.py | 会议 REST API |
| Create | backend/migrations/versions/0016_meeting_agent.py | 会议领域表及索引迁移 |
| Modify | backend/app/models/__init__.py | 注册会议模型 |
| Modify | backend/app/core/enums.py | 增加 meeting 状态、决定和错误枚举 |
| Modify | backend/app/graph/superagent.py | 路由 meeting 场景到会议子图 |
| Modify | backend/app/api/routers/threads.py | 保持会话入口与会议任务关联兼容 |
| Modify | backend/app/main.py | 挂载会议路由和启动检查 |
| Modify | backend/app/services/task_service.py | 投影会议任务摘要和可用操作 |
| Modify | backend/app/services/audit_service.py | 增加会议动作的脱敏摘要约束 |
| Modify | backend/app/providers/bundle.py | 暴露 external_writes=false 的会议能力声明 |

### Frontend

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | frontend/src/views/MeetingView.vue | 会议输入、状态和草稿审阅页面 |
| Create | frontend/src/components/MeetingDraftEditor.vue | 纪要、决策和待办编辑器 |
| Create | frontend/src/components/MeetingSourceList.vue | 来源片段定位与引用展示 |
| Create | frontend/src/api/meeting.ts | 会议 API 客户端 |
| Modify | frontend/src/router/index.ts | 注册会议路由 |
| Modify | frontend/src/App.vue | 增加会议入口并按角色显示 |
| Modify | frontend/src/api/index.ts | 汇总会议 API |
| Modify | frontend/src/types/index.ts | 增加会议领域类型 |
| Modify | frontend/src/views/TaskCenterView.vue | 展示会议任务和恢复动作 |
| Modify | frontend/src/views/AuditView.vue | 支持按会议 ID 查询审计 |

### Tests and Docs

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Create | backend/tests/unit/test_meeting_parser.py | 分段、长度和来源定位单元测试 |
| Create | backend/tests/unit/test_meeting_state.py | 状态迁移和决定门测试 |
| Create | backend/tests/api/test_meeting_flow.py | 会议 API、权限和幂等测试 |
| Create | backend/tests/graph/test_meeting_graph.py | 正常、失败、恢复和不重复生成测试 |
| Create | frontend/src/tests/meeting-workbench.test.ts | 会议页面和编辑器组件测试 |
| Create | frontend/e2e/p2-meeting.spec.ts | 会议创建、审阅、确认和权限 E2E |
| Modify | docs/functional-test-guide.md | 增加 P2 会议实测章节 |
| Create | docs/p2-meeting-acceptance.md | P2 会议验收证据索引 |

## Interfaces

### M1 produces

- MeetingInput：title、content、source_type。
- MeetingSegmentDTO：segment_id、ordinal、start_offset、end_offset、text、locator。
- MeetingDraftDTO：summary、topics、decisions、action_items、source_refs。
- MeetingStatus：CREATED、PROCESSING、DRAFT_READY、REVIEWING、PAUSED、CONFIRMED、REJECTED。

### M2 consumes/produces

- Consumes MeetingInput、MeetingSegmentDTO 和既有 AgentThread/authorization context。
- Produces MeetingRecord、版本化草稿、决定、审计事件和任务摘要。
- API 响应包含 meeting_id、status、version、available_actions、trace_id 和 external_writes=false。

### M3 consumes/produces

- Consumes meeting API DTOs 和既有角色/路由模式。
- Produces可访问输入、来源链接编辑器、确认控件和恢复反馈。

## Batch 1: M1 领域模型、迁移和文本解析

Depends on：P1 B8 本地自动化验证通过；不依赖真实 OA 参数。

### Task 1.1：会议领域模型和迁移

Requirements：会议创建、来源、片段、草稿版本、决定、权限隔离和不可覆盖版本。

Files：meeting_record.py、meeting_source.py、meeting_segment.py、meeting_draft_version.py、meeting_decision.py、0016_meeting_agent.py、迁移测试。

1. Red：添加模型约束、租户索引、版本唯一性和决定幂等唯一性的失败测试。
2. Red Verify：运行迁移测试，确认表和模型尚不存在。
3. Green：创建五个模型、关系、索引和 Alembic 迁移。
4. Green Verify：在独立测试库升级到 head，验证字段、唯一约束和迁移边界。
5. Refactor：统一 UUID、时间戳、JSON 字段和状态常量，确认迁移不触碰既有表数据。

### Task 1.2：文本校验、分段和来源定位

Requirements：非空、长度上限、稳定片段顺序、字符范围和原文可回溯。

Files：meeting_parser.py、meeting.py、test_meeting_parser.py。

1. Red：添加空文本、超长文本、中文/英文段落、无标点长文本和来源范围测试。
2. Red Verify：运行单元测试，确认解析器和稳定错误码不存在。
3. Green：实现输入校验、按段落/句子分段和字符范围定位。
4. Green Verify：验证片段顺序可还原原文，错误输入不产生片段。
5. Refactor：抽取纯函数、限制片段大小并补充敏感摘要不泄露原文测试。

Batch 1 Exit：迁移通过，解析单元测试通过，P1 数据库和前端回归不受影响。

## Batch 2: M2 会议服务、子图和 API

Depends on：Batch 1 通过。

### Task 2.1：结构化会议 DTO 和草稿服务

1. Red：添加草稿字段校验、缺失负责人/截止时间保持不确定、编辑生成新版本、确认/拒绝状态门测试。
2. Red Verify：确认服务不存在或会错误覆盖历史版本。
3. Green：实现 DTO 校验、版本创建、状态迁移和可用操作计算。
4. Green Verify：验证已确认版本不可编辑，拒绝必须保存原因。
5. Refactor：统一状态转换表、错误码和版本快照比较。

### Task 2.2：会议子图和 Mock 生成器

1. Red：添加正常生成、模型失败暂停、重启恢复、重复恢复和外部写工具调用计数为零的测试。
2. Red Verify：确认 SuperAgent 不识别 meeting 场景或无法从 Checkpoint 恢复。
3. Green：实现解析节点、规则/Mock 结构化生成节点、审阅等待节点和恢复路径。
4. Green Verify：验证草稿版本、审计和运行 Span 只写一次，失败进入 PAUSED。
5. Refactor：复用现有图工具、错误映射和运行追踪封装，隔离 meeting 状态字段。

### Task 2.3：会议 REST API 和权限幂等

1. Red：添加完整 API 流程、普通用户隔离、即时撤权、确认门禁、重复决定和 payload 冲突测试。
2. Red Verify：运行 API 测试，确认路由不存在或会绕过权限/幂等。
3. Green：实现路由、依赖注入、权限复核、幂等命令和任务投影。
4. Green Verify：在独立测试库执行会议 API 测试，确认响应包含 trace_id 和下一步动作。
5. Refactor：统一响应 envelope、错误码、分页和审计摘要脱敏。

Batch 2 Exit：会议后端 API/图测试通过，P1 后端全量回归通过，OpenAPI 路由可见。

## Batch 3: M3 前端会议工作台

Depends on：Batch 2 通过。

### Task 3.1：会议 API 类型和页面

1. Red：添加组件测试，覆盖空输入禁用、草稿字段渲染、确认前无外部写入提示和暂停状态按钮。
2. Red Verify：确认会议路由和组件不存在。
3. Green：实现页面、编辑器、来源引用和 API 调用。
4. Green Verify：运行 Vitest 和生产构建，验证错误、加载和状态迁移展示。
5. Refactor：提取状态标签、表单校验和可访问选择器，避免固定等待。

### Task 3.2：路由、任务中心和审计入口

1. Red：添加角色菜单、任务恢复和审计筛选组件测试。
2. Red Verify：确认员工/管理员入口未实现或权限显示错误。
3. Green：接入路由、菜单、任务行操作和会议 ID/trace 查询。
4. Green Verify：运行前端组件测试、构建和现有角色测试。
5. Refactor：统一路由权限提示、加载态和空状态。

Batch 3 Exit：前端组件测试、构建和 P1 角色 E2E 通过。

## Batch 4: M4 验收、恢复和文档

Depends on：Batch 3 通过。

### Task 4.1：会议 E2E 和完整回归

1. Red：添加关键路径 E2E、服务重启恢复、跨租户和即时撤权失败测试。
2. Red Verify：确认未覆盖路径能在当前实现上失败。
3. Green：补齐稳定选择器、测试数据工厂和恢复断言。
4. Green Verify：连续运行两次 E2E，执行后端全量、前端测试和构建。
5. Refactor：清除固定等待，确保测试数据隔离和结果可重复。

### Task 4.2：验收资料和发布边界

1. Red：记录缺失的实测步骤、审计字段和外部写入边界。
2. Red Verify：检查验收文档是否能追溯到测试命令和结果文件。
3. Green：编写验收索引、手动测试步骤、P2 退出条件和未完成项。
4. Green Verify：执行文档中的命令，确认路径、接口和结果文件有效。
5. Refactor：去除重复命令，统一 P1/P2 术语和版本日期。

Batch 4 Exit：P2 会议文本智能体通过自动化、手工验收和代码审查；外部系统写入仍明确标记为后续批次。

## P2 Meeting Exit Criteria

- 会议文本从创建到草稿确认/拒绝的闭环可用。
- 纪要、决策、待办均可编辑并带来源片段。
- 权限、幂等、暂停、恢复、重试和审计测试通过。
- 确认操作不调用外部写工具。
- P1 全量回归保持通过。
- 前端页面、E2E、验收文档和已知限制齐全。
