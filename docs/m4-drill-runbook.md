# M4 本机隔离演练

## 边界与准备

仅使用本机合成数据、独立 Compose project/数据库/卷/目录。不要读取真实 `.env`，不要连接真实 OA、SMTP、企业微信、模型或扫描器。正式部署不加载 M4 overlay。需要本地 Docker、支持 `!reset` 的 Compose v2、后端测试环境，以及已缓存的基础镜像或可用镜像仓库。

入口测试先确认随机的 `oa-m4-<标识>-source` / `destination` 卷和目录不存在，使用空临时 env 文件及环境变量白名单，且内部网络不允许外部服务访问。数据库无主机端口。每次恢复前复核容器标签、数据库名、卷身份和空目标。执行前只读检查已有容器与磁盘空间，不清理未知资源。

## 完整演练

在项目根目录执行：

```powershell
$env:M4_RUN_DOCKER='1'
./backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_m4_recovery_drill.py -q -s
Remove-Item Env:M4_RUN_DOCKER
```

此入口创建两套隔离 PostgreSQL，构建后端镜像，迁移至 head，生成合成用户、历史/在办请假、附件、知识源、checkpoint 和审计导出。它备份源数据并恢复至独立空目标，验证业务与审批幂等，运行基线后端回退及降级/安全/迁移测试。外部依赖均为 Mock 或禁用。附件扫描使用测试替身，未证明真实扫描器可用。

完成后输出 `data/m4-drills/evidence-<标识>`。检查 `recovery.json`、`backup/manifest.json`、`suite.txt`；原始证据含合成业务数据，目录不纳入 Git，报告保存脱敏摘要。`finally` 只移除本次创建且容器身份验证通过的 project/卷，并逐个核对目录位于 `data/m4-drills` 后清理源/目标文件；证据保留。若目标身份无法核实则停止清理，人工核对，禁止改用全局 Docker 清理。

## 分步工具

`backend/scripts/m4_drill.py` 支持 `validate`、`backup`、`verify`、`restore`、`report`，每项均要求显式 `--config`。配置只能位于 `data/m4-drills` 内，字段为 `target` 与 `backup_dir`；不允许放密钥。下面是格式示意，执行者须提供新的唯一身份并先完成隔离资源创建：

```json
{
  "target": {
    "compose_project": "oa-m4-example-source",
    "database_host": "m4-db",
    "database_name": "oa_m4_example_source_test",
    "volume_name": "oa-m4-example-source-pgdata",
    "file_root": "E:/OA AGENT SYSTEM/data/m4-drills/oa-m4-example-source",
    "drill_marker": "M4_DRILL"
  },
  "backup_dir": "E:/OA AGENT SYSTEM/data/m4-drills/example-backup"
}
```

源文件根目录必须有 `attachments`、`knowledge`、`audit_exports` 子目录。完整测试会自动准备它们。目标使用不同 project、数据库、卷和互不嵌套的文件目录；备份不得与源/目标目录重叠。

```powershell
./backend/.venv/Scripts/python.exe backend/scripts/m4_drill.py validate --config data/m4-drills/source.json
./backend/.venv/Scripts/python.exe backend/scripts/m4_drill.py backup --config data/m4-drills/source.json
./backend/.venv/Scripts/python.exe backend/scripts/m4_drill.py verify --config data/m4-drills/source.json
./backend/.venv/Scripts/python.exe backend/scripts/m4_drill.py restore --config data/m4-drills/source.json --source data/m4-drills/source.json --destination data/m4-drills/destination.json
./backend/.venv/Scripts/python.exe backend/scripts/m4_drill.py report --config data/m4-drills/source.json --evidence data/m4-drills/evidence-<标识>/recovery.json
```

清单校验失败不得恢复；目标不空或身份不符不得覆盖；导入失败不开放服务，保留隔离现场或另建空目标重试。该 CLI 不负责创建生产资源、停写、加密、调度或流量切换。

## 前端镜像隔离检查

在仓库根目录构建当前前端并检查静态页面、健康接口和模拟 API 转发：

```powershell
docker build --pull=false -t oa-m4-resilience-frontend:local ./frontend
./backend/.venv/Scripts/python.exe backend/scripts/m4_frontend_smoke.py
```

脚本要求本地已有前端和 `python:3.12-slim` 镜像，使用实际镜像 ID，创建唯一 internal 网络及合成后端，无挂载、无主机端口、不读取 `.env`，结束后只清理本次创建的容器和网络。退出码非零即未通过，不连接预览后端。此检查不代替浏览器业务验收。

镜像 metadata 返回 `text/html` 时，先检查镜像源对应 manifest 的响应类型；不能据此判断业务代码构建失败。可显式从经核实可用的镜像源拉取 Dockerfile 的同一版本，记录 digest，确认本地目标标签不存在后再登记标签并重建。不得静默替换版本或覆盖已有标签；本次没有修改全局 Docker 配置或重启 Docker。根因和实际镜像 digest 见 M4 验收报告。

## 人工降级与补录

AI 关闭后，手工发起、确定性校验、审批、查询和审计继续使用正常 OA 入口；checkpoint 保留。AI 关闭不等于本体故障恢复。本体不可用时无法提交成功命令，采用受控人工记录：

| 字段 | 内容 |
| --- | --- |
| tenant_id / operator_id | 租户与有权操作者 |
| object_id / node_id | 业务对象与审批节点 |
| expected_revision / action | 当时版本与明确动作 |
| operation_id | 唯一且重试时保持不变的补录标识 |
| recorded_at | 包含时区的 UTC 时间 |
| reconciliation_status | PENDING、已核对或人工差异处理 |

演练者人工核对：记录签署、授权、资料保管、紧急审批依据与恢复后处理顺序。恢复后由原有权操作者使用正常审批命令补录，先核对节点和版本；同 operation_id 重试返回既有结果，不重复余额、ledger、event 或 outbox。动作变化、版本冲突、不同操作标识重复办理等转人工差异处理，不强制覆盖状态。按记录逐条核对最终状态、余额、审计与待发通知，完成后更新核对状态。自动测试覆盖补录、去重、冲突拒绝和数据核对；签署、停机期间组织协作及真实人工响应时间仍需现场演练。

## 时间口径和验收边界

记录 `last_verified_commit_at <= failure_at <= recovery_started_at <= service_verified_at`。RPO 为故障到最后已核实且恢复成功的数据点之差；RTO 为故障到恢复后业务验证完成之差，均向上取整到秒。本地测试在目标空数据库就绪后计时，不包括事故发现、采购资源、跨地域传输、DNS、人工决策或切流时间。

参考目标 RPO≤24 小时、RTO≤15 分钟，只能对本次合成数据量和计时范围判断。没有证据的真实服务、HTTPS、域名、防火墙、异地恢复、生产容量、历史生产镜像、每日备份与每周恢复保持未验收。
