# 本地正式 OA 配置

日期：2026-10-22。“正式”指使用持久化账号、权限和内置 OA 业务，不代表已通过生产部署验收。

## 当前配置

- 使用根目录项目，不使用历史预览脚本或其他 worktree。
- 前端：`http://127.0.0.1:5182`；后端：`http://127.0.0.1:8015`。
- `AUTH_PROVIDER=builtin`：启用正式账号、会话和权限，不接受演示身份。
- `OA_PROVIDER=builtin`：项目自身提供 OA 业务权威，不依赖 8091 测试 Bridge，不需要其他企业的接口密钥。
- `AUTH_TENANT_ID=local`：沿用现有数据库，不清库、不导入 Mock 员工和业务。
- 保留模型、嵌入和 SMTP 凭据；通知链接修正为 5182。
- 增量模板：`backend/.env.formal-oa.example`。不得用它覆盖含密钥的 `.env`。
- 2026-10-22 已恢复 DeepSeek 主用、豆包兜底，并补齐真实嵌入开关及 1024 维配置。模型、数据库、邮件认证和企业微信绑定检查见[联调记录](live-service-verification.md)。

## 账号与收件授权

首次初始化管理员 `oa_admin` 和“项目部门”，授予部门管理和业务权限。只初始化空组织，不重置已有口令。初始口令保存在已排除 Git 的 `output/formal-oa-private/initial-admin.env`，不要截图或提交。登录后在账号页面修改初始口令。

管理员授权收件地址为 `oa.demo@example.com`，启用邮件通知。其他成员由组织管理建号，分别维护收件地址；不要把所有员工配置为管理员。保存授权不会自动产生测试业务，也不代表收件箱已送达。

## 启动

1. 启动 Docker Desktop，确认 `oa-agent-db` 健康。
2. 在 `backend` 运行 `$env:OA_BACKEND_PORT='8015'`，再运行 `.\.venv\Scripts\python.exe run.py`。
3. 在 `frontend` 运行 `$env:OA_BACKEND_PORT='8015'`，再运行 `npm run dev -- --host 127.0.0.1 --port 5182 --strictPort`。
4. 打开前端登录；在“通知与站内信 → 授权核对”查看邮箱，在“组织管理”维护成员和角色。

不要用 `m1_preview.py`、`m2_preview.py`、`m3_preview.py` 启动本环境，这些脚本使用隔离验收库及不同开关。

## 本次验证

2026-10-22 通过前端 5182 的 API 代理完成 18 项 HTTP 检查：正式身份和内置 OA 就绪、匿名与 Mock 凭证拒绝、CSRF、管理员登录、身份与组织读取、通知及投递列表、请假/报销/工单/流程列表、收件授权读取、刷新、退出及退出凭证失效。管理员邮箱已绑定且启用。检查不包含实际业务提交、外部邮件投递或生产验收，本轮没有主动发出测试邮件。

## 上线前

当前使用本机 HTTP，`AUTH_COOKIE_SECURE=false` 只适用于 loopback 开发。对外部署必须使用 HTTPS、精确 HTTPS 来源、Secure Cookie、数据库强口令以及备份恢复验证。附件扫描未配置时继续阻止未扫描附件提交；审批流程、额度和工单分派规则需要按实际业务配置发布。企业微信群机器人已启用并绑定项目部门，此前单次测试被接口接受；业务队列投递和成员实际收到提醒仍需核验，操作步骤见 `docs/wecom-notifications.md`。钉钉尚未接通，当前采用企业微信无需重复接入。
