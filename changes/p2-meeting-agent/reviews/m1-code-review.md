# M1 代码审查报告

日期：2026-10-13
审查范围：会议五个 ORM 模型、0016 迁移、Meeting DTO、文本解析器、枚举/模型注册及 M1 测试。
结论：PASS

## 规格符合性

- `meeting_record`、`meeting_source`、`meeting_segment`、`meeting_draft_version`、`meeting_decision` 已独立建模并注册到 `Base.metadata`。
- 迁移 revision `0016` 衔接 `0015`，可重复执行，保留既有数据；业务表含租户、版本、来源范围、幂等和审计所需字段。
- 草稿版本通过 `(meeting_id, version)` 唯一约束不可覆盖；决定通过 `(meeting_id, idempotency_key)` 唯一约束防止重复副作用。
- 解析器拒绝空白内容和超长内容，按标点/换行或片段长度切分，保留稳定顺序、字符范围、哈希和定位；测试验证拼接可还原原文。
- 解析摘要只写片段序号和字符数量，不把会议原文或敏感号码写入摘要。
- 本批没有接入会议 API、图、外部 Provider、OA/任务/日历/邮件写入，符合 M1 scope fence。

## 验证证据

- 解析器定向测试：5 passed。
- 迁移专项测试：2 passed；与既有 MVP 迁移测试合计：6 passed。
- 后端全量串行回归：216 passed，2 个既有弃用警告。
- 前端既有组件测试：19 passed；生产构建成功。
- `git diff --check` 和 Python compileall 均通过。

## 分级问题

### Critical

无。

### Important

无。

### Minor / 后续建议

1. 后续 API/服务批次可增加数据库 CHECK 约束，明确 `end_offset >= start_offset`、状态和决定动作取值；M1 当前通过 DTO/服务层契约控制，尚未需要数据库枚举。
2. 后续 API DTO 测试应覆盖 `MeetingInput` 的额外字段拒绝和待确认字段语义。
3. 当前 `MeetingSegmentDTO.locator` 为字符串，而 ORM `locator` 为 JSONB，以便后续同时保存字符定位和来源元数据；M2 写入服务时应统一序列化格式，避免接口/存储漂移。

## 放行意见

M1 满足执行契约完成定义，可以进入 M2。上述 Minor 项不阻塞 M2，但 M2 的服务/API 实现必须统一 locator 存储格式，并继续保持 `external_writes=false`。
