# M4 本机隔离验证记录

日期：2026-10-22。结论：本地恢复、配置、安全及降级自动化通过；前端容器构建受镜像仓库错误阻塞，M4 最终验收尚未完成。此记录不代表生产上线或部门试点验收通过。

## 环境与数据

- Windows 主机：AMD Ryzen 7 8745HS，8 核 / 16 线程；Docker Linux x86_64，2 CPU、4109402112 字节内存。
- 专用随机 Compose project、PostgreSQL 数据库、持久化卷及 `data/m4-drills` 子目录；数据库无主机端口，网络为 internal。现有预览库未连接、读取或迁移。
- 仅合成用户、两条历史/在办请假、对应附件、一个知识版本、checkpoint 和审计导出；后续回退及回归测试会继续生成临时业务数据。
- schema head：`0029`；PostgreSQL 镜像：`pgvector/pgvector:pg16`，ID `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`。
- 最终后端镜像：`oa-m4-resilience-backend:local`，ID `sha256:b468a3204ec9e9aa08241365d7c92b5dcde58d7069d90910d09e8c82a2df8933`。
- 不读取真实 `.env`。OA、邮件、企业微信、模型、嵌入和扫描器均为替身或禁用，无真实外发。

## 验收映射

| 条目 | 实测证据 | 结论与限制 |
| --- | --- | --- |
| AC-G1 人工降级和备用补录 | `test_m4_degradation.py`：AI 关闭仍能手工办理且保留 checkpoint；备用记录经正常授权命令补录，重复重放无副作用，冲突拒绝 | 自动化通过；停机期间签署、组织协作和人工响应时间仍须现场核对 |
| AC-G2 独立恢复与业务可用 | 真实 PostgreSQL dump/restore 至独立空目标；登录、历史、附件、在办审批、知识、checkpoint、审计导出、readiness、审批重放均通过 | 本次小规模本机合成数据通过；计时范围见下文 |
| AC-G3 注入、工具、外发、日志 | `test_m4_boundaries.py`、SMTP/WeCom 单元与接口回归、工作流权限回归；异常日志和交接上下文敏感标记不泄漏 | 确定性授权边界通过；注入测试验证恶意文本不能授予工具权限，不代表真实模型/恶意文档的全面红队验收 |
| AC-G4 审计检索与原子性 | 审计权限撤销、部门变化、范围检索/导出；event/outbox/ledger 失败注入后业务与成功审计不部分提交 | 所选隔离回归通过；不代表所有审计场景均在本次重跑 |
| AC-G5 配置、持久化、升级/回退 | 三连接同目标、强口令、生产禁 Mock、Compose 认证转发、文件卷配置；空库迁移/重复升级及基线后端回退 | 数据库、配置和后端演练通过；前端容器构建被外部镜像元数据错误阻塞，整项保持部分完成 |

## 实际命令与结果

根目录执行的后端单元回归：

```powershell
./backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_m4_safety.py backend/tests/unit/test_m4_archive.py backend/tests/unit/test_m4_restore.py backend/tests/unit/test_m4_metrics.py backend/tests/unit/test_startup_safety.py backend/tests/unit/test_test_database_safety.py -q
```

结果：107 passed。数据库同目标新增用例先得到 9 failed / 1 passed，再修复运行配置校验；主机、显式端口与库名不一致均被拒绝，默认 5432 归一化通过。Compose 数据库名称一致性用例亦先失败后修复。

完整 Docker 演练命令见 [演练手册](../../../docs/m4-drill-runbook.md)。最终运行配置修正后的证据目录：`data/m4-drills/evidence-6aeb180e9675`；外层 1 passed / 213.28 秒，恢复库内选定回归 81 passed / 41.60 秒。此前扩展演练 `evidence-14aade64ece7` 亦通过。`suite.txt`、`recovery.json` 和 `backup/manifest.json` 保留本地，原始合成归档不纳入 Git。

前端在 `frontend` 目录执行 `npm run build` 通过；`npm run test` 为 25 个文件、119 项通过。已有大 chunk、Vue 测试替身及 Windows asyncio 弃用提示，不作为失败忽略或新增通过证据。

前端镜像命令：`docker build -t oa-m4-resilience-frontend:local ./frontend`。失败位置为 Docker Hub 的 `nginx:1.27-alpine` 元数据解析：`encountered unknown type text/html; children may not be fetched`。重试仍失败，没有以旧镜像或不同基础镜像冒充验证通过。

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

未覆盖：正式服务器、HTTPS/域名/防火墙、真实组织与外部服务、真实模型质量、扫描器、生产容量、并发备份一致性、加密异地保管、每日备份和每周恢复的持续运行。前端镜像构建成功后还需补验并更新任务 6.2；不推送、不合并、不部署。
