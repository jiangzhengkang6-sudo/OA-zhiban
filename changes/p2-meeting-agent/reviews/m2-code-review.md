# M2 会议后端独立代码审查

日期：2026-10-14  
审查批次：M2（会议服务、子图、REST API、权限、幂等、审计和任务投影）  
结论：PASS；可以进入 M3 前端批次。

## 范围与依据

对照 `changes/p2-meeting-agent/execution-contract.md`、`tasks.md`、`specs/meeting-agent.md` 和 `design.md`，逐项检查了 `backend/app/services/meeting_service.py`、会议图和 SuperAgent 路由、会议 API/DTO、任务与通用线程入口、权限和幂等、审计查询/导出、Provider 能力，以及相应的单元、图、API 和恢复测试。检查了场景策略和合法降级配置的最新修复；本审查没有并行运行数据库测试，避免干扰主开发线程的独立测试库。

仓库尚无可用 BASE/HEAD 提交：待审文件均为未跟踪文件，无法给出真实 SHA 范围或 `git diff BASE..HEAD`。环境中没有 `ssf` 命令，故无法生成真实工作流 review receipt；此文件是持久审查报告，不冒充自动回执。

## 优点与规格符合性

- 会议命令以租户、用户和所有者重新核验权限；通用线程发消息、人工中断恢复、任务转人工等入口不能绕过会议草稿审阅接口（`meeting_service.py`、`thread_service.py`、`interrupt_service.py`、`task_service.py`）。
- 创建、生成、编辑、决定均通过统一幂等记录保存首次响应；成功回放在实时策略门之前返回快照，但仍先复核身份和资源权限。版本冲突、确认/拒绝状态、拒绝原因和草稿来源片段均有校验（`meeting_service.py`）。
- 会议子图在 PostgreSQL Checkpoint 上保留人工审阅中断；生成失败进入 PAUSED，恢复与事务回滚后的再次编辑均有 HTTP 回归测试。会议确认只保存平台内记录，Provider 声明 `external_writes=false`（`meeting_graph.py`、`providers/bundle.py`）。
- 审计写入的是哈希、片段数量和结果摘要；会议事件查询按租户过滤，导出快照及后续访问绑定租户范围（`audit_repo.py`、`audit_export.py`）。
- 会议命令实际读取场景策略和降级状态；测试采用公开配置允许的 `new_task_action=fallback`、`inflight_action=pause`，覆盖关停、新请求阻断、原键回放和恢复后执行（`meeting_service.py:74`、`tests/api/test_meeting_http.py:477`）。

## 问题分级

### Critical

无。

### Important

无。

### Minor / 后续说明

1. `backend/app/services/meeting_service.py:83-85`：运维降级的在途 `pause` 当前以 503 阻止本次会议命令，并保留原业务状态；它不会像普通对话的 `thread_service.py` 那样把任务状态写成 PAUSED。这不会执行被禁止的生成/编辑，也能在降级恢复后重试，但 M3 页面和运维说明应写明“降级阻断”和“生成依赖失败后的可重试 PAUSED”是两种不同情形，避免把 503 当成已有恢复按钮的 PAUSED。
2. `backend/app/services/meeting_service.py:370-390`：无显式键的失败重试会稳定回放原失败结果；真正发起下一次重试需要新的显式键。M3 的重试按钮应为每次新尝试产生并保留一个键，以免用户反复收到旧快照。现有服务行为符合幂等安全要求。

## 验证与放行

主开发线程已反馈最新定向 HTTP 测试通过；本审查未独立运行数据库测试。M2 的全量回归数值应以主开发线程本轮实际结果更新进 `m2-progress.md`，不得沿用修复前的 238 项数字作为最新证据。没有发现阻断 M3 的 Critical/Important 问题。M3 继续保持外部写入关闭，并在前端实现降级错误提示与显式重试键。
