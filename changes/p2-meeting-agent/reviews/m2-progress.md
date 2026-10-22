# M2 会议后端进度与验证

日期：2026-10-14

## 已实现

- 会议领域模型与 0016 迁移、文本校验和有序来源片段、结构化且保留不确定性的草稿。
- 会议 REST API：创建、列表、读取、生成、编辑、确认、拒绝、重新生成和暂停重试；会议任务关联 AgentThread。
- 每次业务访问重新获取权限和租户/所有者范围；并发版本门、统一幂等命令和首次结果快照。
- SuperAgent 会议路径、PostgreSQL Checkpoint 的人工审阅中断、失败恢复、生成结果对账，以及事务回滚后编辑重建审阅点。
- 审计和运行 Span 保留摘要与 trace；会议事件按租户过滤，导出绑定创建时的租户范围；暂停事件标记失败和错误码。
- 会议 Provider 能力标记 `text_input=true, external_writes=false`；确认只写平台内记录，测试对外部写工具设有禁止调用断言。
- 会议创建与写命令接入实时 meeting 场景策略和降级控制；禁用或不允许继续时返回 503，恢复后可重新执行。

## 验证证据

- 独立测试库 `oa_agent_test`，设置 `ENVIRONMENT=test`、`ALLOW_TEST_DATABASE_RESET=true`；测试串行执行，开发数据库未清理。
- 定向：`python -m pytest tests/api/test_meeting_flow.py tests/api/test_meeting_http.py tests/graph/test_meeting_graph.py tests/unit/test_provider_bundle.py tests/migrations/test_meeting_agent.py -q --tb=short` → **29 passed, 2 warnings**。
- 后端全量：`python -m pytest tests/unit tests/migrations tests/api tests/graph tests/security tests/recovery -q --tb=short` → **238 passed, 4 warnings in 93.75s**。警告来自既有审计导出 `datetime.utcnow()`。
- 前端 `http://127.0.0.1:5173` 返回 200；后端 `http://127.0.0.1:8001/healthz` 返回 `status=ok`。运行中的后端若未热更新，仍需重启以加载最新代码。
- 补齐 meeting 场景开关和降级门后，重新运行同一后端全量命令 → **239 passed, 4 warnings in 97.20s**。

## 语义与待复核项

- 无客户端键的重试以首次暂停 trace 作为稳定命令键：重复请求回放上次结果。上次重试仍失败时，发起一次新的尝试需提供新的显式幂等键；前端每次主动重试必须生成并保持一个键。
- M2 独立代码审查已完成并判定 PASS，详见 `m2-code-review.md`；M3 前端审查修复正在复审，M4 验收尚未开始。
- meeting 的场景关闭/降级阻止新写命令，保留已有会议的授权读取；降级时返回结构化 503，不改写已有业务状态。
- 仓库目前没有提交历史，无法提供真实 SHA 范围；工作流 CLI 不在环境中，因此只记录实际命令和结果，不伪造状态机回执。
