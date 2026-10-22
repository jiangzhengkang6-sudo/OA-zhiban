# M3 前端会议工作台独立复审

范围：复核 `m3-code-review.md` 的三个 Important 和两个 Minor，并检查新增测试与 M3 契约。依据 `execution-contract.md`、`specs/meeting-agent.md`、`tasks.md`。当前是 **uncommitted working tree**，无可用 base/head SHA；直接阅读工作树，未伪造 SHA 或 `ssf` receipt。执行方报告前端单测 32 passed、生产构建通过、P1 角色 E2E 5 passed；本次只读审查未重跑。

## Strengths / 已解决项

- 丢响应重试：`meetingApi.commandKey` 以用户、命令种类和载荷形成 sessionStorage 槽，收到业务结果后才释放；创建、生成、保存、决定、暂停重试均调用 `replayable`（`frontend/src/api/meeting.ts:7-21`；`frontend/src/views/MeetingView.vue:53-96`）。同载荷丢响应重发可复用键，暂停响应已确认后可发起新尝试。真实 command-slot 单测和页面重试单测相互补充；旧 Important 关闭。
- 审计入口仅管理员可见，后端仍独立执行权限校验（`MeetingView.vue:28,112`）；旧 Important 关闭。
- 路由切换时旧详情响应由序号和目标 ID 双重排除，命令使用捕获的 ID 且返回后核验路由（`MeetingView.vue:36-51,82-96`）；旧 Important 关闭。
- 会议状态新增中文标签；摘要级来源可多选且保存前校验来源属于当前会议（`frontend/src/utils/status.ts:20-24`；`frontend/src/components/MeetingDraftEditor.vue:41-43`；`MeetingView.vue:19-26`）；旧两个 Minor 基本关闭。
- 保存前深复制响应式草稿（`MeetingView.vue:82`），避免 Vue proxy 进入 JSON 请求/幂等载荷计算或请求中修改对象；现有单测验证修改摘要被传入保存 API。

## Issues

### Critical

无。

### Important

1. **会议状态筛选展示为空，实际有匹配任务。** `frontend/src/views/TaskCenterView.vue:14,40-41`，`frontend/src/utils/status.ts:20-24`。下拉项新增了 `DRAFT_READY`、`REVIEWING`、`CONFIRMED` 等会议领域状态，并原样传给 `/tasks?status=`；服务端 `backend/app/services/task_service.py:139-140` 却按 `AgentThread.status` 筛选。会议 `DRAFT_READY/REVIEWING` 对应 `WAITING_HUMAN`，`CONFIRMED` 对应 `COMPLETED`（`backend/app/services/meeting_service.py:170-175`），因此选择“待审阅/已确认”必然返回 0，即使任务卡片显示该状态。按会议场景提供与服务端契约一致的筛选映射或改造服务端按会议领域状态过滤，补真实查询/契约测试；不可仅按 mock 的 `taskApi.list` 调用断言。

2. **详情加载失败后出现不可完成的创建流程。** `frontend/src/views/MeetingView.vue:39-43,59-69,105-108`。打开无效、撤权或网络失败的 `/meetings/:meetingId` 时，`meeting` 置空、`loading` 结束，于是 `!meeting` 分支显示创建表单；若用户创建成功，`create()` 因原 URL 中 `meetingId` 非空跳过 `apply()` 和跳转，界面仍停在错误详情 URL，且平台已经新建会议。应区分列表创建态与详情加载失败态，仅无 ID 时显示创建表单；详情错误给重试/返回列表控件。添加 GET 拒绝场景的组件测试。

### Minor

1. **审计角色测试依赖之前测试留下的 localStorage。** `frontend/src/tests/meeting-workbench.test.ts:36-45,115-122`。`beforeEach` 未固定当前用户，员工断言靠默认/执行顺序；之前运行管理员用例或测试并行隔离变化会使其失败/掩盖真实角色差异。测试开始显式 `setCurrentUserId('u_emp_001')`，并在结束恢复。

2. **单测对命令键端到端组合仍偏轻。** `meeting-workbench.test.ts:10-12,78-100` 将 `commandKey` mock 为固定或预排的键，因此页面测试能验证调用关系但不能证明 sessionStorage 的真实槽在视图重新挂载后复用。`meeting-command-key.test.ts:7-24` 覆盖真实槽，同样未结合真实 HTTP 丢响应；建议 M4 E2E 中覆盖相同载荷创建的响应丢失/重复提交不产生第二条记录。此处为测试强化建议，不否定已解决的旧 Important。

## Assessment

**Verdict: FAIL；Ready to merge: No。** 上次五项反馈的实现均有实质修复，但任务状态筛选契约错位和详情错误分支仍是用户可触发的功能问题。先修这两项 Important 并复审，再进入依赖 M3 通过的 M4。仓库无提交区间，无法生成真实 SHA receipt。
