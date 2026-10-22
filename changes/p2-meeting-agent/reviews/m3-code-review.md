# M3 前端会议工作台独立审查

审查范围：M3 会议 API/类型、工作台、草稿编辑器、来源列表、路由菜单、任务中心、审计入口及相关组件测试；对照 `execution-contract.md`、`specs/meeting-agent.md`、`design.md`、`tasks.md`。当前为 **uncommitted working tree**，仓库尚无可用 base/head commit SHA，故没有可核验的提交区间或 `ssf execution review` SHA receipt。本报告直接审阅工作树文件。测试结果按执行方提供的证据：25 项前端单测、5 项 P1 角色 E2E 和生产构建通过；本次只读审查未重新运行测试。

## Strengths

- 工作台的操作显隐依据服务端 `available_actions`，编辑使用 `expected_version`，未保存更改时阻止人工决定；确认提示清楚说明只保存平台内结果（`MeetingView.vue:15-19,52-64,78-82`）。
- 草稿编辑器支持议题、决策、待办增删和来源引用编辑，来源链接可定位原文，缺失负责人或期限以待确认呈现（`MeetingDraftEditor.vue:9-32,41-53`）。
- 会议任务从业务 ID 打开专属工作台，避免通用任务重试路径绕开会议显式幂等键（`TaskCenterView.vue:18-25`）。
- 组件测试覆盖创建门槛、版本保存、来源、暂停降级反馈、任务恢复和审计筛选；接口形状与后端会议 DTO 基本一致。

## Issues

### Critical (Must Fix)

无。

### Important (Should Fix)

1. **传输失败后的新幂等键可能重复副作用**。`frontend/src/views/MeetingView.vue:44,49-53,63`，`frontend/src/api/meeting.ts:9`。每次点击生成新的键；若首次创建、保存或决定已由服务端提交，只是响应超时/丢失，再次点击会以新命令执行。创建会产生第二个会议；保存会因旧 `expected_version` 冲突，确认会因状态已变而失败，用户无法得到首次成功回放。API 客户端未持有创建命令键（第 9 行）也放大此问题。建议在同一载荷/版本的未确定命令期间保留键并重放，同步读取服务器状态确认结果后才允许明确发起新命令；暂停的显式“新尝试”另行生成新键。新增模拟已提交但网络失败的测试。

2. **普通员工的审计按钮通往必然拒绝的页面**。`frontend/src/views/MeetingView.vue:79`。按钮对每个会议可见，但审计查询仅管理员授权（`backend/app/api/routers/audit.py:65`），普通员工打开后只会收到 403，且 `AuditView.vue:101-113` 不展示可用的错误状态。规格要求非管理员受限，前端应仅在管理员身份显示此入口，或增加明确的受限反馈；管理员按会议 ID 查询保留。补充员工/管理员的可见性测试。

3. **旧详情响应可能覆盖新路由并把命令送往另一会议**。`frontend/src/views/MeetingView.vue:27-38,49-63`。用户在 `/meetings/A` 尚未加载完时转到 `/meetings/B`，两个 `load()` 并行，A 的晚返回会覆盖 B 的 `meeting`/`draft`。此时标题和草稿显示 A，但命令使用当前 `meetingId` B；相同版本时可能把 A 的编辑稿保存到 B。给加载引入请求序号或 AbortController，响应只在路由 ID 仍匹配时应用；路由切换期间清空旧详情，并在动作执行时捕获、核对目标 ID。添加交错响应组件测试。

### Minor (Nice to Have)

1. **任务卡片会议状态是原始枚举**。`frontend/src/utils/status.ts:7-20`。任务投影返回 `CREATED`、`DRAFT_READY`、`REVIEWING`、`PROCESSING`、`CONFIRMED` 等会议领域状态，`StatusTag` 从 `STATUS_MAP` 找不到中文标签，将显示原始代码。加入会议状态映射，但注意 `REJECTED` 与其他场景共享且现有标签仍合理。

2. **草稿来源汇总不能编辑**。`frontend/src/components/MeetingDraftEditor.vue:39-53`。用户可编辑单项引用，但 `modelValue.source_refs` 保持生成时的初值；摘要改写引用到其他来源时无法修正该字段。将摘要/草稿级来源设为可编辑的多选，并要求至少一个来源，或明确从当前选择计算来源。现有编辑测试仅覆盖候选增删，未验证来源多选提交。

## Recommendations

先修复三项 Important 并补回归测试，再做复审。Minor 可在 M3 内一并处理，特别是草稿级来源引用以满足退出准则。网络不确定结果与主动新尝试必须在界面语义上分开。

## Assessment

**Ready to merge? No (M3 gate: fail).** 核心界面和基础测试具备，但幂等重试、审计入口权限和跨路由异步竞态均有用户可触发的错误路径，应修复后复审。由于没有 base/head SHA，不提供伪造的 `ssf` receipt 命令。
