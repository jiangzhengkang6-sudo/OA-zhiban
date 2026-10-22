# M1 账号与组织底座验收

日期：2026-10-18。范围：正式 PRD V1.5 的 M1，B1–B5。本记录用于本地工程验收，不代表正式 OA 上线。

## 交付内容

- 迁移 0023 新增 10 张账号、组织、权限及会话表；不改历史业务归属。
- Argon2id 口令、固定 HS256 JWT、摘要刷新令牌轮换、重放撤销、登录限流、改密和退出。
- 部门、岗位、成员、直属上级、角色及本人/本部门资源权限；最后管理员、防环及跨组织引用保护。
- 禁用/调岗/授权变化由请求、工具、后台及提交前再次检查；生命周期与审计同事务，禁用保留待交接状态。
- 中文登录、个人改密、组织管理、权限菜单；access 仅内存，refresh 为 HttpOnly Cookie。

## 本地预览

前端：http://127.0.0.1:5193；后端：http://127.0.0.1:8013。使用 oa_identity_m1_preview_test，身份 builtin，业务 OA/文本/嵌入均为 Mock；与原有预览及业务库隔离。

账号和随机口令见本机 `E:/OA AGENT SYSTEM/data/verification/m1/preview-login.txt`，该目录已忽略。管理员初始只拥有组织管理权，不能自动读取敏感业务；可在组织管理中建成员、配置部门和角色。

独立后端启动脚本：`backend/scripts/m1_preview.py`。它仅连接固定隔离库并迁移该库，不读取应用数据库 URL 或模型密钥。脚本每次启动生成新的临时 JWT 密钥；重启后需重新登录。前端从 frontend 启动：

```powershell
$env:OA_BACKEND_PORT='8013'
npm run dev -- --host 127.0.0.1 --port 5193
```

## 正式身份配置准备

独立环境配置 AUTH_PROVIDER=builtin、AUTH_TENANT_ID、至少 32 字节的独立 AUTH_JWT_SECRET、精确 AUTH_ALLOWED_ORIGINS。AUTH_COOKIE_SECURE 默认为 true；仅 localhost/127.0.0.1 开发允许 false。默认 access 最长 7200 秒，refresh 绝对期限最长 7 天。不要将真实密钥填入 .env.example。

目标数据库需先备份并评估升级，再在 backend 执行 `python -m alembic upgrade head`；本轮没有对现有业务库执行该操作。首管理员通过 `python -m app.cli.bootstrap_admin --username <账号>` 显式初始化，终端隐藏输入至少 12 位密码；没有公共注册或默认密码。本轮仅验证 CLI 帮助和隔离库初始化。

当前正式 OA Provider 尚未就绪，production 启动门禁仍阻止 Mock 身份或 Mock OA；以上配置准备不能解除该门禁。

## 验证命令

在仓库根运行后端验证，所有数据库目标必须一致且为隔离库；禁止与另一后端测试进程共享测试数据库。

```powershell
$env:ENVIRONMENT='test'
$env:ALLOW_TEST_DATABASE_RESET='true'
$env:DATABASE_URL='postgresql+asyncpg://oa:oa@localhost:5433/oa_identity_m1_test'
$env:DATABASE_SYNC_URL='postgresql+psycopg://oa:oa@localhost:5433/oa_identity_m1_test'
$env:CHECKPOINTER_URL='postgresql://oa:oa@localhost:5433/oa_identity_m1_test'
$env:LLM_PROVIDER='mock'
$env:EMBEDDING_PROVIDER='mock'
$env:OA_PROVIDER='mock'
$env:AUTH_PROVIDER='mock'
& backend/.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short
```

在 frontend 运行 `npm test`、`npm run build`。独立预览启动后运行 `npx playwright test --config=playwright.m1.config.ts`。不要把 ALLOW_TEST_DATABASE_RESET 写入正式环境配置。

## 结果与覆盖

后端全量 516 项通过；全量后补充的空来源缓存断言所在兼容组 10 项通过；前端 74 项通过，类型检查和构建成功；最终后端重启后桌面/手机浏览器 2 项通过。没有跳过后端测试。

最终计数和失败修复记录见 [验证报告](../changes/department-oa-foundation/reviews/verification.md)。原始输出与桌面/手机截图在 `data/verification/m1/`；浏览器关闭 trace，截图不包含口令或令牌。

| 需求 | 主要证据 |
| --- | --- |
| M1-01 持久化与迁移 | test_identity_foundation.py：0022 历史数据、升到 0023、重复升级；test_identity_models.py |
| M1-02 初始化与登录 | test_credentials.py、test_identity_sessions.py：初始化、并发失败锁定、来源限流 |
| M1-03 会话 | test_identity_sessions.py：轮换、并发重放撤销、退出、Origin/CSRF、改密 |
| M1-04 动态权限 | test_identity_authorization.py、test_identity_business_compatibility.py：禁用/版本/提交/后台/来源检查 |
| M1-05 组织与范围 | test_organization_access.py、兼容测试：跨租户、防环、最后管理员、真实部门列表/详情/版本 |
| M1-06 生命周期 | test_organization_access.py：会话撤销、启用不复活、授权变化、审计失败回滚 |
| M1-07 前端 | auth-session/auth-client/organization-access 测试；桌面与手机浏览器流程 |
| M1-08 隔离兼容 | test_startup_safety.py、后端全量回归；builtin 禁止 Mock OA 与不安全生产配置 |

## 人工复核

1. 登录后管理部门、岗位、成员及角色，角色写权限应包含对应读权限；尝试部门或上级循环应拒绝。
2. 员工登录后刷新页面恢复；直接访问组织管理应跳回有权页面，后端管理 API 同样拒绝。
3. 调整员工部门后旧部门数据不再可见；停用后已登录页面再次访问需重新登录，启用不恢复旧会话。
4. 退出后直接访问受保护地址需登录；管理权不隐含敏感业务读取权。

上述浏览器关键流程已自动验证；真实员工导入、生产部署和业务流程用户验收未执行。

## 后续范围

- M2 人工审批流程、M3 正式 OA Provider/通知及真实数据迁移尚未实施；待交接标记不代表业务已转交。
- builtin 的旧知识管理、策略、审计查询/导出、运维与工单/审批业务明确 503；生命周期审计仍保存。Mock 模式原演示行为保留。
- 合同参与人、工作任务批次和来源、报表来源保留更窄的业务条件；部门权限不保证所有既有协作场景已开放。
- 同窗口刷新单飞；多标签页同时使用同一 refresh 可能触发严格重放保护，需重新登录。
- 未做生产压测、渗透测试、正式备份恢复演练或全套旧浏览器集成验收；本轮未发付费模型请求，未改用户 .env 或原业务数据库。

工作流工具缺失已获用户批准人工替代；审查由当前实施者完成，不冒充独立审查、机器收据或正式归档确认。
