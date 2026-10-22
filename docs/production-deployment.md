# 生产部署

本手册描述目标环境的部署条件。2026-10-22 的 M4 只完成本机合成数据隔离演练；服务器、真实外部服务、HTTPS、生产容量及持续备份尚未验收。正式部署不得使用 `docker-compose.m4.yml`、M4 合成账号或测试口令。

## 配置与持久化

- 使用明确的 Compose project 和受保护配置文件，命令均带 `--env-file <配置文件>` 与 `-p <项目名>`。不要输出完整配置或密钥到日志。
- 配置 `ENVIRONMENT=production`、`AUTH_PROVIDER=builtin`、明确的 `AUTH_TENANT_ID`、足够强的 `AUTH_JWT_SECRET`、精确 HTTPS `AUTH_ALLOWED_ORIGINS`、`AUTH_COOKIE_SECURE=true`。外部 OA 使用已经能力探测的适配器；自建本体使用 `OA_PROVIDER=builtin`。
- 设置非默认强数据库口令。当前 Compose 将同一口令插入三个连接 URL，口令应使用 URL 安全字符；数据库名通过 `POSTGRES_DB` 同时供容器、连接与健康检查使用。更改该值不会重命名已有卷中的数据库，禁止把修改变量当作数据库迁移。
- 生产启动会检查异步、同步、checkpoint 连接目标一致，并拒绝弱口令和 Mock 身份/OA 组合。AI 尚未完成接入验收时设置 `AI_ENABLED=false`，人工 OA 仍可用。
- `oa_pgdata` 保存 PostgreSQL；`oa_files` 挂载 `/app/data`，其中附件为 `leave_attachments`、知识文件为 `knowledge_files`。卷名由项目名隔离。只给前端入口放行；数据库的现有开发端口仅绑定主机回环，生产环境还应通过专用覆盖配置取消该端口发布。
- 目标环境完成 HTTPS 入口、网络白名单、防火墙、扫描器和通知服务配置及验收后再开放真实业务。最低资源需求须通过目标环境容量测试确定，本地小数据演练不提供容量保证。

## 启动与检查

以下参数由部署者填写，不能直接沿用本地预览或 M4 目标。部署前保留版本、迁移 head、备份编号及文件目录记录。

```powershell
docker compose --env-file <受保护配置文件> -p <明确项目名> -f docker-compose.yml config --quiet
docker compose --env-file <受保护配置文件> -p <明确项目名> -f docker-compose.yml build backend frontend
docker compose --env-file <受保护配置文件> -p <明确项目名> -f docker-compose.yml up -d --wait
docker compose --env-file <受保护配置文件> -p <明确项目名> -f docker-compose.yml ps
```

容器启动执行 `alembic upgrade head`，不执行表清理或 downgrade。检查后端 `/healthz`、前端 `/healthz` 与 `/api/readiness`，并实际验证登录、历史、附件、人工发起审批、审计和通知状态。readiness 通过只代表它覆盖的依赖检查，不能代替这些业务验收。日志检查须脱敏。

## 备份与恢复

备份集须包含 PostgreSQL 自定义格式 dump（含业务、审计、LangGraph checkpoint）、附件、知识源文件、审计导出和非敏感配置清单。记录一致性时间、大小、SHA-256、应用版本和迁移 head。跨数据库及文件的一致性需在暂停写入的窗口或经验证的快照机制下保证；M4 的静止合成数据不能证明在线并发备份一致性。

数据库操作通过显式 Compose project 的 `exec -T db` 定位服务，不依赖固定容器名。不要用 PowerShell 文本重定向处理二进制 dump；用经过验证的二进制流归档工具。当前 `backend/scripts/m4_drill.py` 只允许 `data/m4-drills` 中的隔离目标，不能作为生产备份程序直接使用。

恢复必须先验证备份清单与目标身份，再写入独立的新空库和新文件目录。禁止覆盖源库，禁止使用 `pg_restore --clean --if-exists` 清理原业务库。恢复使用事务与遇错退出；失败目标保持隔离，排查后另建空目标重试。成功后核对登录、历史、附件哈希、知识源、在办审批、checkpoint、审计、余额及幂等重放，记录 RPO/RTO，再由环境负责人安排流量切换。

数据副本应加密存储并复制到异机介质；密钥在独立受控系统保管。每日备份、保留期、失败告警、每周恢复演练及异地恢复须由目标环境持续运行并留证。当前没有将单次同机备份认定为这些能力已完成。

## 应用回退

执行 [回滚手册](rollback-runbook.md) 中的兼容矩阵检查。只切换经验证兼容的应用版本，保留数据库和文件卷；不允许数据库 downgrade、删除卷或清空业务数据。本地隔离演练细节见 [M4 演练手册](m4-drill-runbook.md)。
