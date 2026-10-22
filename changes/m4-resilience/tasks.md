# M4 实施任务

## File Structure

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| Modify | `docker-compose.yml` | 移除全局固定容器名与弱密码默认值，限制数据库端口绑定并保持明确配置。 |
| Create | `docker-compose.m4.yml` | 为隔离演练覆盖 Compose 设置，不发布数据库主机端口并使用独立持久化卷。 |
| Modify | `backend/app/db/migrations.py` | 补齐正式式运行配置的数据库凭据及 Provider 安全校验。 |
| Modify | `backend/tests/unit/test_startup_safety.py` | 覆盖弱/缺省凭据与 Mock Provider 的失败关闭行为。 |
| Create | `backend/app/ops/__init__.py` | 声明 M4 运维演练工具包。 |
| Create | `backend/app/ops/m4_safety.py` | 校验演练身份、Compose project、数据库、卷与文件目标白名单。 |
| Create | `backend/app/ops/m4_archive.py` | 创建、清单化并校验 PostgreSQL/文件备份集。 |
| Create | `backend/app/ops/m4_restore.py` | 将已验证备份恢复至新的独立空目标并执行目标保护。 |
| Create | `backend/app/ops/m4_metrics.py` | 计算和格式化恢复演练 RPO/RTO 及证据数据。 |
| Create | `backend/scripts/m4_drill.py` | 提供 M4 演练命令入口、参数解析和步骤编排。 |
| Create | `backend/tests/unit/test_m4_safety.py` | 覆盖隔离目标和危险目标拒绝规则。 |
| Create | `backend/tests/unit/test_m4_archive.py` | 覆盖备份清单、哈希和不完整归档拒绝规则。 |
| Create | `backend/tests/unit/test_m4_restore.py` | 覆盖独立空目标检查与恢复命令保护。 |
| Create | `backend/tests/unit/test_m4_metrics.py` | 覆盖 RPO/RTO 公式、边界和缺证据情况。 |
| Create | `backend/tests/integration/test_m4_recovery_drill.py` | 在唯一隔离 Compose project 中验证迁移、备份、恢复、重放和业务可用性。 |
| Create | `backend/tests/recovery/test_m4_degradation.py` | 验证 AI 关闭人工办理和本体故障后的备用记录/补录对账路径。 |
| Create | `backend/tests/security/test_m4_boundaries.py` | 覆盖 M4 提示注入、越权访问与敏感日志边界。 |
| Create | `backend/tests/migrations/test_m4_upgrade_rollback.py` | 覆盖隔离库迁移、重复升级与兼容应用回退边界。 |
| Modify | `docs/production-deployment.md` | 修订经验证的配置、迁移、备份及恢复操作步骤并标明环境边界。 |
| Modify | `docs/rollback-runbook.md` | 修订兼容应用回退、向前修复和独立目标恢复决策步骤。 |
| Create | `docs/m4-drill-runbook.md` | 记录本机隔离演练前置检查、命令、核对表和失败处理。 |
| Create | `changes/m4-resilience/reviews/m4-verification.md` | 记录实际执行命令、环境、日志、RPO/RTO、验收结果及未覆盖项。 |

## Interfaces

- `m4_safety.validate_drill_target(target: DrillTarget) -> ValidatedTarget`：输入显式 Compose project、数据库地址/名称、卷标识、文件根目录和演练标记；只返回通过白名单核验的目标，否则抛出不含凭据的 `UnsafeTargetError`。导出 `DrillTarget`、`ValidatedTarget`、`UnsafeTargetError`。
- `m4_archive.create_backup(target: ValidatedTarget, output_dir: Path, captured_at: datetime) -> BackupManifest`：调用 pg_dump 并归档配置列出的持久化目录，输出包含版本、时间、组件、相对路径、大小和 SHA-256 的 `manifest.json`。导出 `BackupManifest` 与 `BackupEntry`。
- `m4_archive.verify_backup(backup_dir: Path) -> BackupManifest`：校验 manifest、路径范围、组件完整性和哈希；无效时抛出 `InvalidBackupError`，不得执行恢复副作用。
- `m4_restore.restore_backup(backup: BackupManifest, source: ValidatedTarget, destination: ValidatedTarget) -> RestoreResult`：仅接受身份不同且为空的恢复目标；返回数据库/文件恢复结果和逐项核验状态。导出 `RestoreResult`、`RestoreCheck`。
- `m4_metrics.calculate_recovery_metrics(failure_at: datetime, last_verified_commit_at: datetime, recovery_started_at: datetime, service_verified_at: datetime) -> RecoveryMetrics`：返回 RPO、RTO 秒数及各 PRD 目标的布尔结果；缺失时间由调用端记录为未覆盖，不伪造默认值。导出 `RecoveryMetrics`。
- `m4_drill.py` CLI 接口：`python scripts/m4_drill.py validate|backup|verify|restore|report --config <isolated-config>`。所有命令要求显式隔离配置；调用 Compose 时固定传入基础文件与 `docker-compose.m4.yml`、唯一 `-p` project 和临时合成环境文件；数据库不发布主机端口。目标校验失败使用非零退出码，成功输出仅含脱敏摘要与证据目录。
- 批次交接：Batch 1 产出通过验证的 `ValidatedTarget`；Batch 2 产出安全的正式式 Compose/运行配置；Batch 3 产出 `BackupManifest`；Batch 4 消费 manifest 并产出 `RestoreResult`；Batch 5 消费恢复和降级结果并产出 `RecoveryMetrics`；Batch 6 消费全部结果并产出验收报告。

## Tasks

Each TDD phase is an atomic 2-5 minute step. Split any larger change before execution.

### Batch 1: 隔离运行基线

- [x] 1.1 增加演练目标类型与安全拒绝规则

Files: `backend/app/ops/__init__.py`, `backend/app/ops/m4_safety.py`, `backend/tests/unit/test_m4_safety.py`

Interfaces: Produces `DrillTarget`, `ValidatedTarget`, `UnsafeTargetError`, `validate_drill_target()`；其余任务只接受 `ValidatedTarget`，不接受原始字符串路径或数据库地址。

TDD phases:
1. RED: 为缺少演练标记、非白名单数据库名和重复源/目标身份各写一个失败测试。
2. GREEN: 定义类型与 `validate_drill_target()`，只实现这三条拒绝路径。
3. RED: 增加未批准 Compose project、已占用卷和越界文件根路径测试。
4. GREEN: 实现 project/卷/路径边界校验，并保证异常不包含 URL 凭据。
5. VERIFY: 运行 `pytest tests/unit/test_m4_safety.py`；REFACTOR: 合并重复规范化逻辑并复跑该文件。

Depends on: None。

- [x] 1.2 解除 Compose 固定资源名和危险数据库默认值

Files: `docker-compose.yml`, `docker-compose.m4.yml`, `backend/tests/unit/test_m4_safety.py`

Interfaces: Compose project 名由 `docker compose -p` 提供；`POSTGRES_PASSWORD` 必须显式提供；M4 overlay 必须移除基础 Compose 的数据库端口映射；不改变业务容器运行命令。

TDD phases:
1. RED: 增加 Compose 配置断言，固定 `container_name` 或默认弱密码存在时失败。
2. GREEN: 删除固定容器名，将密码改为必填插值。
3. RED: 增加 M4 overlay 不发布数据库主机端口且资源名唯一的配置测试。
4. GREEN: 新增 M4 overlay 清空数据库 host port 映射，使 project 前缀为卷/网络/容器加唯一作用域。
5. VERIFY: 用隔离合成 env 执行 `docker compose config --quiet` 和配置断言；REFACTOR: 删除重复/无效 Compose 设置并重验。

Depends on: Batch 1 Task 1.1。

### Batch 2: 生产式配置拒绝危险值

- [x] 2.1 为正式模式增加凭据与 Mock Provider 安全校验

Files: `backend/app/db/migrations.py`, `backend/tests/unit/test_startup_safety.py`

Interfaces: `validate_runtime_configuration(settings) -> None` 延续现有接口；新增拒绝条件使用 `RuntimeError`，错误消息不得包含实际凭据。

TDD phases:
1. RED: 为生产模式弱/默认数据库口令及 Mock 身份/OA Provider 写测试。
2. GREEN: 增加正式模式口令强度与 Provider 组合校验。
3. RED: 增加安全配置合法值可启动和错误不泄露凭据的断言。
4. GREEN: 保持 development/test Mock 预览兼容，只在 production/prod 严格拒绝。
5. VERIFY: 运行 `pytest tests/unit/test_startup_safety.py`；REFACTOR: 统一环境判定与错误常量并复跑。

Depends on: Batch 1 Task 1.2。

### Batch 3: 备份创建与完整性校验

- [x] 3.1 定义备份清单和文件内容校验

Files: `backend/app/ops/m4_archive.py`, `backend/tests/unit/test_m4_archive.py`

Interfaces: Produces `BackupEntry`, `BackupManifest`, `InvalidBackupError`，并实现 manifest 序列化、相对路径约束、目录文件 SHA-256 校验。

TDD phases:
1. RED: 写入有效 manifest 往返、缺字段和绝对路径拒绝测试。
2. GREEN: 实现 manifest 数据类型及安全解析。
3. RED: 写入文件缺失、哈希不符和路径穿越测试。
4. GREEN: 实现相对路径、文件大小和 SHA-256 校验，失败不修改归档。
5. VERIFY: 运行 `pytest tests/unit/test_m4_archive.py`；REFACTOR: 抽取共享哈希函数并复跑。

Depends on: Batch 1 Task 1.1。

- [x] 3.2 生成数据库与受管文件备份集

Files: `backend/app/ops/m4_archive.py`, `backend/tests/unit/test_m4_archive.py`, `backend/scripts/m4_drill.py`

Interfaces: `create_backup(target, output_dir, captured_at) -> BackupManifest` 仅消费 `ValidatedTarget`；CLI `backup` 调用该函数，日志仅输出备份 ID、组件和状态。

TDD phases:
1. RED: mock subprocess 测试 pg_dump 失败时不留下成功 manifest。
2. GREEN: 实现自定义格式 pg_dump 调用并将 stdout 写入隔离归档目录。
3. RED: 测试附件、知识源、审计导出目录归档及合成 Mock 状态文件策略。
4. GREEN: 从显式配置采集受管目录，生成 manifest；禁止收集 `.env`、Git、缓存和密钥文件。
5. VERIFY: 运行备份单测及 `python scripts/m4_drill.py backup --help`；REFACTOR: 清理临时文件并验证失败原子性。

Depends on: Batch 1 Task 1.1, Batch 3 Task 3.1。

### Batch 4: 独立目标恢复与业务核验

- [x] 4.1 实现恢复目标保护和备份前置校验

Files: `backend/app/ops/m4_restore.py`, `backend/tests/unit/test_m4_restore.py`

Interfaces: Produces `RestoreResult`, `RestoreCheck` 与 `restore_backup()`；调用 `verify_backup()`，只接受经验证的 manifest 和两个不同的 `ValidatedTarget`。

TDD phases:
1. RED: 为源目标等于目的目标、非空未知目标及白名单外目标写拒绝测试。
2. GREEN: 实现恢复前目标身份和空目标检查，危险目标不调用 subprocess。
3. RED: 为被篡改/不完整备份恢复时无任何目标写入写测试。
4. GREEN: 强制完整性验证先于任何 pg_restore 或文件复制。
5. VERIFY: 运行 `pytest tests/unit/test_m4_restore.py`；REFACTOR: 合并目标断言并复跑。

Depends on: Batch 1 Task 1.1, Batch 3 Task 3.1。

- [x] 4.2 恢复数据库和文件到新的空白目标

Files: `backend/app/ops/m4_restore.py`, `backend/tests/unit/test_m4_restore.py`, `backend/scripts/m4_drill.py`

Interfaces: `restore_backup(backup, source, destination) -> RestoreResult`；CLI `restore` 要求显式 `--source` 与 `--destination` 配置，不提供原地恢复选项。

TDD phases:
1. RED: mock pg_restore 测试参数不含 `--clean` 且目标库名精确来自已验证目标。
2. GREEN: 实现数据库恢复命令并记录退出状态，不在 shell 拼接凭据。
3. RED: 测试数据库恢复失败时不复制文件、文件复制失败时不返回成功。
4. GREEN: 实现归档文件恢复、每项结果记录和安全清理本次临时目录。
5. VERIFY: 运行恢复单测及 CLI help；REFACTOR: 统一清理/错误报告并复跑。

Depends on: Batch 4 Task 4.1。

- [x] 4.3 计算恢复指标

Files: `backend/app/ops/m4_metrics.py`, `backend/tests/unit/test_m4_metrics.py`

Interfaces: Produces `RecoveryMetrics`, `calculate_recovery_metrics()`；RPO/RTO 单位为整数秒，并分别给出是否满足 24 小时/15 分钟目标。

TDD phases:
1. RED: 写入恰好等于目标、低于目标和超出目标的边界测试。
2. GREEN: 实现 UTC 时间正规化及差值计算。
3. RED: 写入时点顺序错误、时区缺失和关键证据缺失测试。
4. GREEN: 拒绝不合法顺序；缺少证据由 CLI 记为未覆盖，不生成默认指标。
5. VERIFY: 运行 `pytest tests/unit/test_m4_metrics.py`；REFACTOR: 保持输出稳定并复跑。

Depends on: Batch 4 Task 4.2。

### Batch 5: 集成、安全和降级演练

- [x] 5.1 端到端隔离备份恢复与幂等核验

Files: `backend/tests/integration/test_m4_recovery_drill.py`, `backend/app/ops/m4_safety.py`, `backend/app/ops/m4_archive.py`, `backend/app/ops/m4_restore.py`

Interfaces: 消费已验证的 Compose project 和 `RestoreResult`；测试只在唯一 `*_test` 数据库、唯一 project 和临时文件根目录运行，并通过现有三连接 `validate_test_targets()` 保护数据库。

TDD phases:
1. RED: 建立合成请假/审批/附件/知识文件/checkpoint 数据基线和恢复后核对断言。
2. GREEN: 串接迁移、备份、独立恢复与健康检查，确保恢复对象存在且可读。
3. RED: 增加已完成审批重放不重复更改余额、事件、审计或 outbox 的断言。
4. GREEN: 通过现有领域 API 重放命令并核验权威状态及文件下载权限。
5. VERIFY: 先运行该集成测试单项；REFACTOR: 保证临时 project/目录在成功和失败时都清理且不触碰其他资源。

Depends on: Batch 4 Task 4.2, Batch 4 Task 4.3。

- [x] 5.2 验证 AI 降级及本体故障备用流程

Files: `backend/tests/recovery/test_m4_degradation.py`, `docs/m4-drill-runbook.md`

Interfaces: 测试产出 AI 关闭人工办理结果及备用记录对账清单；不新增外发服务接口。

TDD phases:
1. RED: 在 `ai_enabled=false` 下验证手工发起、校验、审批、查询和审计均可完成。
2. GREEN: 复用现有人工 OA API/服务，不增加 AI 依赖。
3. RED: 为本体不可用时备用记录字段、恢复后去重补录与差异核对写场景测试。
4. GREEN: 将人工记录模板和对账步骤写入演练手册，并为可自动验证部分提供断言。
5. VERIFY: 串行运行降级测试；REFACTOR: 对不可自动化的人工步骤明确标注“演练者核对”，不可报告为自动通过。

Depends on: Batch 5 Task 5.1。

- [x] 5.3 验证安全边界和迁移回退

Files: `backend/tests/security/test_m4_boundaries.py`, `backend/tests/migrations/test_m4_upgrade_rollback.py`, `docker-compose.yml`, `backend/app/db/migrations.py`

Interfaces: 测试复用现有认证、附件权限、审计及 Alembic 接口；回退测试只验证应用兼容矩阵，不执行数据库 downgrade。

TDD phases:
1. RED: 覆盖提示注入、越权附件/工具访问和敏感日志扫描的 M4 演练用例。
2. GREEN: 仅在发现 M4 范围内缺陷时修复既有实现并增加回归断言。
3. RED: 覆盖空白隔离库升级、重复 upgrade、readiness 和兼容应用版本回退用例。
4. GREEN: 通过显式版本矩阵阻止不兼容旧应用启动，不增加破坏性 downgrade。
5. VERIFY: 串行运行该批安全/迁移测试并保存脱敏日志；REFACTOR: 移除冗余 fixture，复跑失败用例。

Depends on: Batch 2 Task 2.1, Batch 5 Task 5.1。

### Batch 6: 手册、回归与验收报告

- [x] 6.1 修订部署和回滚操作手册

Files: `docs/production-deployment.md`, `docs/rollback-runbook.md`, `docs/m4-drill-runbook.md`

Interfaces: 文档命令必须与 `m4_drill.py` CLI 和 Compose 配置一致；每个破坏性动作注明确认条件、目标身份和禁止操作。

TDD phases:
1. RED: 为部署/回滚文档建立命令一致性检查清单，记录当前未覆盖步骤。
2. GREEN: 更新生产式配置、迁移健康检查及兼容应用回退步骤。
3. RED: 校验备份/恢复手册覆盖数据库、checkpoint、附件、知识文件、报告及恢复后业务核对。
4. GREEN: 编写隔离演练步骤、失败恢复和未覆盖项说明。
5. VERIFY: 按手册在隔离环境逐条执行关键命令；REFACTOR: 删除与实际 CLI 不符的旧步骤。

Depends on: Batch 5 Task 5.1, Batch 5 Task 5.2, Batch 5 Task 5.3。

- [x] 6.2 完成 M4 串行验收与证据报告

2026-10-22：本地数据库/恢复/安全/降级及前端测试通过。前端镜像加速地址返回 HTML 的故障已定位；显式拉取相同基础版本后构建成功，修复健康接口重复响应头，容器隔离 HTTP 检查通过。最终 Git 基准已按实际建立时间登记；详见 `reviews/m4-verification.md` 及 `reviews/git-baseline-provenance.md`。本条仅指本机范围验收，不包含生产部署或归档授权。

Files: `changes/m4-resilience/reviews/m4-verification.md`, `backend/scripts/m4_drill.py`, `backend/tests/integration/test_m4_recovery_drill.py`, `backend/tests/recovery/test_m4_degradation.py`

Interfaces: 消费测试日志、Docker 镜像/迁移版本、备份 manifest、恢复核验和 RecoveryMetrics；产出逐条映射 AC-G1–AC-G5 的报告。

TDD phases:
1. RED: 为 AC-G1–AC-G5 建立验收矩阵，并将缺少证据的条目标记未覆盖。
2. GREEN: 串行执行配置检查、迁移、安全、备份恢复及降级演练并归档脱敏输出。
3. RED: 校验 RPO/RTO 时间证据、业务恢复断言和限制是否齐全。
4. GREEN: 填写实际结果，只将实测通过项标记通过；明确异机/每日/每周及生产环境未验收。
5. VERIFY: 复核报告链接、命令和日志一致性，执行最终只读状态检查；REFACTOR: 删除无证据或超出本地隔离范围的结论。

Depends on: Batch 6 Task 6.1。

## Requirement Mapping

| Requirement | Tasks |
| --- | --- |
| 演练环境必须隔离 | 1.1, 1.2, 5.1 |
| 备份覆盖范围完整且可校验 | 3.1, 3.2, 4.1 |
| 恢复写入独立目标并核对业务 | 4.1, 4.2, 5.1 |
| RPO/RTO 必须基于实测 | 4.3, 6.2 |
| 升级与回退不得破坏业务数据 | 1.2, 2.1, 5.3, 6.1 |
| 安全边界与审计通过验证 | 2.1, 5.3, 6.2 |
| 降级路径保持人工业务可用 | 5.2, 6.2 |

## 执行进度

- 2026-10-22：用户授权建立 Git 基线并继续 M4；基线 `8cb8fc6` 已包含 Batch 1，最终审查需补充该快照的检查。正式配置校验提交 `bfe9fb6`。
- Batch 2–4：三连接凭据校验、完整性清单、自定义格式备份、独立空目标事务恢复、RPO/RTO 计算与 CLI 已实现；相关单测 95 passed。真实 `.env`、预览数据库与外部服务未使用。
- Compose 环境隔离测试发现 Windows 插件依赖 `ProgramFiles`，通过单变量验证后加入系统路径白名单；M4 专用卷改为与校验器一致的 project 前缀，数据库端口仅回环绑定。下一步执行隔离 PostgreSQL 和业务恢复集成演练。
