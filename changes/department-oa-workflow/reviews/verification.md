# M2 联合验证报告

日期：2026-10-19。范围：已批准执行契约 B1–B6；当前实施者人工执行及复核。

## 最终结果

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 后端联合回归 | 608 passed，0 failed，0 error，0 skipped；241.16s，退出码 0 | `data/verification/m2/backend-regression.xml` |
| 前端全套 | 22 文件、87 tests passed；8.27s，退出码 0 | 本轮 Vitest 实际输出 |
| 类型检查及生产构建 | `vue-tsc -b && vite build` 退出码 0；Vite 5.88s | 本轮构建实际输出 |
| 桌面/手机浏览器 | 6 passed，0 skipped/failed/flaky；53.5s，退出码 0 | `data/verification/m2/browser-result.json` |

后端命令明确排除 `backend/tests/migrations/test_identity_foundation.py` 的 1 项历史测试：该测试会另外创建随机 `oa_migration_<uuid>_test`，超出本轮仅允许的两个数据库。它未在本次运行，未计入 608，不是 pytest skipped。M2 迁移用例在授权库的独立 schema 中验证 0023→0024、身份数据保持、重复升级、13 表约束及拒绝降级；通用迁移用例另验证 head、模型结构与旧 MVP 数据保持。此次不声称未排除的后端全量测试通过。

## 运行方式

从项目根目录运行后端；事先显式覆盖 `ENVIRONMENT=test`、`ALLOW_TEST_DATABASE_RESET=true` 及三个数据库连接变量，使其全部指向 `localhost:5433/oa_workflow_m2_test`。`LLM_PROVIDER=mock`、`LLM_FALLBACK_PROVIDER=none`、`EMBEDDING_PROVIDER=mock`、`OA_PROVIDER=mock`、`AUTH_PROVIDER=mock`；正式身份测试在各自隔离上下文显式使用 builtin。数据库套件串行运行。

```powershell
& ./backend/.venv/Scripts/python.exe -m pytest backend/tests --ignore=backend/tests/migrations/test_identity_foundation.py --junitxml=data/verification/m2/backend-regression.xml -q
```

在 `frontend` 目录分别执行：

```powershell
npm test -- --run
npm run build
npx playwright test --config playwright.m2.config.ts
```

浏览器使用 Edge、单 worker，访问专用前端 5194/后端 8014 和 `oa_workflow_m2_preview_test`。未访问付费模型、真实邮件或生产系统。原始报告、截图和本地账号文件位于已忽略目录，口令/令牌不写入文档。

## 覆盖与复核

| 维度 | 结论 | 实际依据 |
| --- | --- | --- |
| 完整性 | PASS（M2 契约范围） | M2-01…13 均有任务和验证映射，见 tasks.md 与验收文档 |
| 正确性 | PASS（本次执行范围） | 状态/版本、权限、跨年/重叠、独立会话与进程并发、回滚、恢复、AI 关闭及端到端验证 |
| 设计一致性 | PASS | 0024 仅扩张；统一命令事务和锁序；正式表权威；AI/旧 Mock 隔离；通知保持 PENDING |
| 范围控制 | PASS | 仅授权隔离库/端口；真实配置、原库、生产发送和部署未进入本次范围 |

浏览器覆盖结构化创建/发布流程与分支/抄送、额度调整、员工管理入口隔离及直达 403、驳回修改重提/批准归档、会签两人/或签一人、转交及旧人失效、手机提交/撤回/归档和弹窗/页面宽度。已查看工作台、手机申请与额度弹窗截图；无阻断操作的布局问题。

独立进程 AI 关闭用例实际保留检查点，禁止图/模型/外部 OA 调用仍完成办理；调度竞争用例由两个独立 Python 进程同时扫描后再启动第三进程补扫，事件不重复。业务审计/outbox/台账故障注入验证整体回滚和原键重试。

## 已知限制

- 后端 17 条警告涉及 Windows Selector policy 弃用、既有 audit export 的 `datetime.utcnow` 和邮件解析 `re.split` 参数。前端测试有独立挂载路由/图标桩提示；构建有混合静态/动态导入和主包体积提示。此次没有声称零警告。
- 初次回归/浏览器失败与修复见 [B6 复核](B6.md)，最终结果以本报告为准；不累加定向与全套的重复测试数量。
- 仅实施者复核；ssf 脚本不可用、仓库无 HEAD，按已批准方式不伪造独立审查、机器 gate、Git SHA 或正式归档。
- 未进行真实组织/额度导入、生产扫描器部署、通知投递、生产部署或备份恢复演练。PRD V1.5 整体尚未验收。

本报告完成 M2 工程验证记录；不替代试点负责人确认或后续 M3/M4 验收。
