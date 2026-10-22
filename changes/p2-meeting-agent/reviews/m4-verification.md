# M4 本地验证结果

日期：2026-10-14。工作目录：`E:\OA AGENT SYSTEM`，分支 `codex/p2-meeting-agent`。以下为本轮命令的实际终端结果汇总，不是 CI 原始日志；仓库尚无提交或 SHA。

| 命令 | 实测结果 |
| --- | --- |
| `cd frontend; npm run test:e2e`（最终测试改动后连续第一次） | 12 passed (9.4s)，退出码 0 |
| `cd frontend; npm run test:e2e`（最终测试改动后连续第二次） | 12 passed (9.6s)，退出码 0 |
| `cd frontend; npx playwright test --config playwright.integration.config.ts --repeat-each=2` | 2 passed (11.9s)，退出码 0；真实 5174 → 8002 → `oa_agent_test` |
| `cd frontend; npm run test:e2e`（集成测试隔离后复核） | 12 passed (9.5s)，退出码 0；不收集真实集成用例 |
| `cd frontend; npx playwright test --config playwright.integration.config.ts`（隔离后复核） | 1 passed (8.1s)，退出码 0 |
| `cd frontend; npm run test`（集成测试改动后复核） | 34 passed，退出码 0；既有 B4 图标 stub 警告 |
| `cd frontend; npm run build`（集成测试改动后复核） | `vue-tsc -b && vite build` 成功，退出码 0；大 chunk 警告 |
| `cd backend;` 同下方显式 `_test` 环境，全量 pytest（集成测试改动后复核） | 240 passed, 4 warnings in 96.79s，退出码 0 |
| `cd frontend; npm run test` | 34 passed，退出码 0；既有 B4 图标 stub 警告 |
| `cd frontend; npm run build` | `vue-tsc -b && vite build` 成功，退出码 0；大 chunk 警告 |
| `cd backend; $env:ENVIRONMENT='test'; $env:ALLOW_TEST_DATABASE_RESET='true'; $env:DATABASE_URL='postgresql+asyncpg://oa:oa@localhost:5433/oa_agent_test'; $env:DATABASE_SYNC_URL='postgresql+psycopg://oa:oa@localhost:5433/oa_agent_test'; $env:CHECKPOINTER_URL='postgresql://oa:oa@localhost:5433/oa_agent_test'; python -m pytest tests/unit tests/migrations tests/api tests/graph tests/security tests/recovery -q --tb=short` | 240 passed, 4 warnings in 94.44s，退出码 0 |
| `cd backend;` 同上环境，`python -m pytest tests/api/test_meeting_http.py::test_confirmation_never_calls_external_oa_writers -q --tb=short` | 1 passed，退出码 0 |

Playwright 的 JSON 输出为 `frontend/data/verification/b8-browser/result.json`（普通套件）及 `frontend/data/verification/meeting-integration/result.json`（真实集成套件），均随下一次运行覆盖。连续运行及后端/组件/构建的结果由本报告记录，原始终端输出未另行归档；不得称其为持久 CI 记录。前端 `http://127.0.0.1:5173/meetings` 最终检查返回 HTTP 200。

默认浏览器会议用例使用 `/api/` 拦截。新增的专用集成用例不拦截 API，使用隔离端口 5174/8002，显式 `ENVIRONMENT=test`、Mock Provider 和三个同指 `oa_agent_test` 的连接地址，覆盖真实创建、生成、来源、编辑 v2、确认及刷新恢复。默认配置排除此用例，避免普通 `npm run test:e2e` 意外写开发库；专用服务测试结束后退出，5173/8001 保持监听。浏览器断言 `external_writes=false` 和无任务/日历/邮件 HTTP 请求，外部 OA 方法零调用的证据仍来自后端单测。未清空开发库、未删除 Docker 卷。人工 T19-T23、真实 OA/正式部署均未执行。
