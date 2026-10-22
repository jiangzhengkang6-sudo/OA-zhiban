# P2 会议文本智能体验收记录

日期：2026-10-14。范围：`changes/p2-meeting-agent/execution-contract.md` 的 M1-M4，本地 Mock 模型和 OA；人工实测及正式资料后补。

本批可复核的命令与结果汇总见 `changes/p2-meeting-agent/reviews/m4-verification.md`；浏览器末次运行的机器可读结果见 `frontend/data/verification/b8-browser/result.json` 和 `frontend/data/verification/meeting-integration/result.json`（后续运行会覆盖）。后端和构建的原始终端输出未另行保存，不能视为 CI 记录。

## 自动化结果

| 层级 | 命令/证据 | 结果 |
| --- | --- | --- |
| 浏览器 | `cd frontend; npm run test:e2e`，连续两次 | 每次 12/12（P1 角色 5，P2 会议 7） |
| 真实浏览器集成 | `cd frontend; npx playwright test --config playwright.integration.config.ts --repeat-each=2` | 2/2；隔离 5174/8002 服务和 `oa_agent_test` 数据库，默认套件排除此测试 |
| 前端组件 | `cd frontend; npm run test` | 34/34；既有 B4 图标 stub 警告 |
| 前端构建 | `cd frontend; npm run build` | 通过；已有大 chunk 提示 |
| 后端 | `cd backend; $env:ENVIRONMENT='test'; $env:ALLOW_TEST_DATABASE_RESET='true'; $env:DATABASE_URL='postgresql+asyncpg://oa:oa@localhost:5433/oa_agent_test'; $env:DATABASE_SYNC_URL='postgresql+psycopg://oa:oa@localhost:5433/oa_agent_test'; $env:CHECKPOINTER_URL='postgresql://oa:oa@localhost:5433/oa_agent_test'; python -m pytest tests/unit tests/migrations tests/api tests/graph tests/security tests/recovery -q --tb=short` | 240/240，4 条 `datetime.utcnow()` 弃用警告 |

模拟浏览器用例在 `frontend/e2e/p2-meeting.spec.ts` 拦截 `/api/` 请求，验证页面流程和请求契约；覆盖创建、来源编辑确认、拒绝、刷新恢复、丢失响应后的幂等键、暂停重试、撤权错误提示和管理员审计跳转。另有 `frontend/e2e/p2-meeting-integration.spec.ts` 不拦截 API，真实走前端代理、FastAPI 和测试数据库，覆盖创建、生成、编辑新版本、确认及刷新恢复。专用配置通过 `backend/run.py` 使用 Windows 兼容事件循环，明确将所有数据库连接指向 `oa_agent_test`；普通套件不收集此用例。浏览器断言无非预期任务/日历/邮件请求，不能单独证明后端零外部写入。

后端独立 `_test` 数据库用例 `backend/tests/api/test_meeting_http.py` 覆盖角色即时撤销、跨租户、版本与命令幂等、审计租户隔离、Checkpoint 重启及事务回滚后恢复；`test_confirmation_never_calls_external_oa_writers` 对 Mock OA 的五个写方法断言零调用，API/服务测试断言 `external_writes=false`。这些是 Mock 环境证据，非真实 OA 联调。

## 人工验收与限制

- `docs/functional-test-guide.md` T19-T23：**待人工实测**。请填写实际结果、meeting_id、trace_id 和复现步骤。
- 正式 API、真实 OA 资料和外部写入验收：**未提供、未执行**。会议确认仅保存平台内结果；禁止将本阶段描述为真实任务、日历、邮件或 OA 已创建。
- Docker 镜像构建/正式部署演练、真实环境授权与数据保护核查：**待完成**。
- 工作流 `ssf` 命令/脚本在当前环境不可用，仓库尚无提交，故无可验证的 wave receipt 或 base/head SHA；不能伪造归档状态。本文件只记录实际运行证据，批次审查另见 `changes/p2-meeting-agent/reviews/`。

结论：M4 本地自动化门槛通过；代码复审结论以 `changes/p2-meeting-agent/reviews/m4-code-review.md` 为准。Batch 4 的完整 Exit 还要求人工验收，T19-T23 与正式上线门槛尚未通过。
