# M4 本机隔离验证记录

日期：2026-10-22。结论：本地恢复、配置、安全、降级及前端容器自动化通过；此前镜像构建缺口已解决，最终审查基准已按实际建立时间登记。此记录只覆盖已批准的本机隔离验收，不代表生产上线或部门试点验收通过。

## 环境与数据

- Windows 主机：AMD Ryzen 7 8745HS，8 核 / 16 线程；Docker Linux x86_64，2 CPU、4109402112 字节内存。
- 专用随机 Compose project、PostgreSQL 数据库、持久化卷及 `data/m4-drills` 子目录；数据库无主机端口，网络为 internal。现有预览库未连接、读取或迁移。
- 仅合成用户、两条历史/在办请假、对应附件、一个知识版本、checkpoint 和审计导出；后续回退及回归测试会继续生成临时业务数据。
- schema head：`0029`；PostgreSQL 镜像：`pgvector/pgvector:pg16`，ID `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`。
- 最终后端镜像：`oa-m4-resilience-backend:local`，ID `sha256:b468a3204ec9e9aa08241365d7c92b5dcde58d7069d90910d09e8c82a2df8933`。
- 最终前端镜像：`oa-m4-resilience-frontend:local`，ID `sha256:1514333a5b0683734a4892c16478632c177106a638bb02f5797dac488eb1ba86`。
- 不读取真实 `.env`。OA、邮件、企业微信、模型、嵌入和扫描器均为替身或禁用，无真实外发。

## 验收映射

| 条目 | 实测证据 | 结论与限制 |
| --- | --- | --- |
| AC-G1 人工降级和备用补录 | `test_m4_degradation.py`：AI 关闭仍能手工办理且保留 checkpoint；备用记录经正常授权命令补录，重复重放无副作用，冲突拒绝 | 自动化通过；停机期间签署、组织协作和人工响应时间仍须现场核对 |
| AC-G2 独立恢复与业务可用 | 真实 PostgreSQL dump/restore 至独立空目标；登录、历史、附件、在办审批、知识、checkpoint、审计导出、readiness、审批重放均通过 | 本次小规模本机合成数据通过；计时范围见下文 |
| AC-G3 注入、工具、外发、日志 | `test_m4_boundaries.py`、SMTP/WeCom 单元与接口回归、工作流权限回归；异常日志和交接上下文敏感标记不泄漏 | 确定性授权边界通过；注入测试验证恶意文本不能授予工具权限，不代表真实模型/恶意文档的全面红队验收 |
| AC-G4 审计检索与原子性 | 审计权限撤销、部门变化、范围检索/导出；event/outbox/ledger 失败注入后业务与成功审计不部分提交 | 所选隔离回归通过；不代表所有审计场景均在本次重跑 |
| AC-G5 配置、持久化、升级/回退 | 三连接同目标、强口令、生产禁 Mock、Compose 认证转发、文件卷配置；空库迁移/重复升级及基线后端回退；前端镜像构建与隔离 HTTP 检查 | 本机范围通过；历史生产镜像与目标服务器仍未验收 |

## 实际命令与结果

根目录执行的后端单元回归：

```powershell
./backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_m4_safety.py backend/tests/unit/test_m4_archive.py backend/tests/unit/test_m4_restore.py backend/tests/unit/test_m4_metrics.py backend/tests/unit/test_startup_safety.py backend/tests/unit/test_test_database_safety.py -q
```

结果：107 passed。数据库同目标新增用例先得到 9 failed / 1 passed，再修复运行配置校验；主机、显式端口与库名不一致均被拒绝，默认 5432 归一化通过。Compose 数据库名称一致性用例亦先失败后修复。

完整 Docker 演练命令见 [演练手册](../../../docs/m4-drill-runbook.md)。最终运行配置修正后的证据目录：`data/m4-drills/evidence-6aeb180e9675`；外层 1 passed / 213.28 秒，恢复库内选定回归 81 passed / 41.60 秒。此前扩展演练 `evidence-14aade64ece7` 亦通过。`suite.txt`、`recovery.json` 和 `backup/manifest.json` 保留本地，原始合成归档不纳入 Git。

前端在 `frontend` 目录执行 `npm run build` 通过；`npm run test` 为 25 个文件、119 项通过。已有大 chunk、Vue 测试替身及 Windows asyncio 弃用提示，不作为失败忽略或新增通过证据。

前端镜像命令：`docker build -t oa-m4-resilience-frontend:local ./frontend`。失败位置为 Docker Hub 的 `nginx:1.27-alpine` 元数据解析：`encountered unknown type text/html; children may not be fetched`。重试仍失败，没有以旧镜像或不同基础镜像冒充验证通过。

### 镜像缺口的修复与补验

已确认配置中的加速地址 `docker.1panelproxy.com` 对 `/v2/library/nginx/manifests/1.27-alpine` 返回 `200 text/html`，正常 registry 地址会返回镜像元数据或 JSON 认证挑战。本次未修改全局 Docker 配置、重启 Docker 或替换 Dockerfile 基础版本；从明确指定的 `docker.m.daocloud.io/library/` 拉取同名版本，确认目标本地标签不存在后登记为 Dockerfile 所需标签。已下载 digest：

- Node：`sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d`。
- Nginx：`sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10`。

`docker build --pull=false -t oa-m4-resilience-frontend:local ./frontend` 成功。首轮 HTTP 检查发现 `/healthz` 同时发送 `application/octet-stream` 和 `text/plain` 两个 Content-Type；将 `add_header Content-Type` 改为 `default_type text/plain` 后，重新构建并执行：

```powershell
./backend/.venv/Scripts/python.exe backend/scripts/m4_frontend_smoke.py
```

退出码 0。检查 `/healthz` 内容与唯一 Content-Type、首页与 `/assistant` 的 SPA 回退、入口 JS/CSS 内容及类型、GET 查询参数/代理头、POST 原文、后端 404 透传、停掉合成后端后的 502，以及故障期间静态健康接口仍可用。仅创建 `oa-m4-frontend-cb4a52b0b04e` 内部网络及无挂载、无主机端口的临时容器，全部已清理；未连接实际后端或数据库。该检查属于 HTTP 容器验收，不声称完成新的浏览器交互验收。

`npm audit --registry=https://registry.npmjs.org --json` 报告开发工具链 6 项（3 moderate、1 high、2 critical；涉及 Vite/Vitest 及其依赖），原镜像源不支持 audit 接口。`npm audit --omit=dev --registry=https://registry.npmjs.org --json` 为 0 项。运行镜像仅复制静态产物，没有 Node/Vite/Vitest 服务；开发工具链升级另行跟踪，不把本次静态镜像验收描述为全部依赖安全验收。未执行破坏性自动升级，未暴露开发/测试服务。

### 最终审查基准

参见 [基准登记](git-baseline-provenance.md)：2026-10-22T16:09:13+08:00 在已有根提交上新建本地 `main`；这不是恢复了不存在的历史主分支。最终审查使用工具支持的旧版/手动分支规则，覆盖 `git merge-base main HEAD` 到实现提交的完整范围；Batch 1 保持基准快照补查的限制。此前拒绝记录及失败结论保留在 Git 历史，正式审查结果以 `.superpowers/sdd/reviews/final.md` 和工具记录为准。

手册 CLI 的 `validate`、`verify`、`report` 已对保留的合成配置及证据执行通过；实际 `backup`、`restore` 由完整演练调用相同底层实现。生产命令未执行。

## 恢复时间证据

| 字段 | UTC 时间 |
| --- | --- |
| 最后已核实且恢复的数据提交 | 2026-10-22T07:54:33.643350+00:00 |
| 备份采集 | 2026-10-22T07:54:34.201147+00:00 |
| 故障点 | 2026-10-22T07:54:34.911955+00:00 |
| 恢复开始 | 2026-10-22T07:54:34.911959+00:00 |
| 恢复后业务验证结束 | 2026-10-22T07:54:41.310908+00:00 |

RPO = ceil(故障点 - 最后已核实提交) = 2 秒；RTO = ceil(验证结束 - 故障点) = 7 秒。本次在 PRD 24 小时 / 15 分钟目标内。计时开始前目的数据库已经就绪，未计入事故发现、资源准备、异地传输、DNS、人工决策或切流；静止合成数据备份未证明并发写入一致性。

归档 261616 字节、12 个条目；备份 ID：`056f9f62f971451aa9a4757a7a17f37b`；manifest SHA-256：`6568C33AF00F96424764046DFA54118AF047A34DFE798B8F40E1CBCB92A66AC8`。哈希用于完整性检查，不提供来源真实性签名。最终只读检查未发现本次 M4 容器残留。

## 回退及交付边界

回退只验证 Git `8cb8fc625d3bb1c175f17cb0321e32837171a6b2` 的后端源码与 schema `0029`：启动、读写、提交审批及幂等重放通过。未知版本或 schema 不匹配被阻止。未执行数据库 downgrade；未证明历史生产镜像兼容。

原始基线已包含 Batch 1。`reviews/batch1-review.md` 是当时无 Git HEAD 的快照复核补充，不能当作历史机器审查凭据。最终代码审查须绑定真实 Git 范围，不编造旧 SHA。

未覆盖：正式服务器、HTTPS/域名/防火墙、真实组织与外部服务、真实模型质量、扫描器、生产容量、并发备份一致性、加密异地保管、每日备份和每周恢复的持续运行。本次不推送、不合并、不部署。

原有本地实现提交：`a1f7c706ce8074d5957815e3e4d46651b97d9764`。该快照的镜像构建及审查登记失败记录保留于 `01610ad`。本次修复后的完整范围、当前审查结论与工具记录见 `../.superpowers/sdd/reviews/final.md`；不追认缺失的历史凭据。
