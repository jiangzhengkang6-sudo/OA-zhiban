# P3 本地工程验收

日期：2026-10-14。范围：工作任务、只读报表、私有合同辅助审查。实际仓库为 `E:/OA AGENT SYSTEM`，分支为 `codex/p3-business-agents`。本文件记录本地工程交付，不作为生产准入、真实模型质量或法务验收。

## 已实现行为

- 工作任务：从授权的已确认会议、工单和结束审批提取候选；人工补齐负责人和截止时间、确认风险后创建；支持开始、进度、改派、完成、取消、归档和两阶段私有逾期提醒。
- 报表：三个登记指标集，经人工批准计划后执行真实 PostgreSQL 参数化只读查询；图表读取不可改写的数据快照，摘要仅允许定性文字与合法指标引用；保存不可变版本并在平台内发布。
- 合同：粘贴文本或上传 TXT/文本 PDF，保留私有原文及可校验证据；四节点 LangGraph 编排、指定复核人逐项处理风险并确认；支持版本历史和受控恢复。
- 长合同实际接入 `deepagents==0.4.11`，不是占位接口。Mock 模型运行真实 DeepAgents 计划和分块工具；只允许 `write_todos` 与 `read_contract_block`，默认文件、执行及子代理工具不获得执行权限。
- 三个场景具备独立开关、当前身份和租户检查、幂等账本、版本检查、事务决定、脱敏审计、通用接口旁路防护和预算限制。增量迁移 head 为 `0022`。

## 验证结果

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 后端完整回归 | 420 passed，4 warnings，195.14 秒 | 本次开发的实际终端运行；未另存全量 JUnit，不虚构日志文件 |
| 前端单元测试 | 58 passed，13 个测试文件 | `npm test` 实际终端结果；收尾阶段再次通过 |
| 类型检查和生产构建 | exit 0 | `npm run build`；既有 bundle 超过 500 KB 警告仍存在 |
| 独立合成评测 | 39 passed，0 failures/errors/skipped | `backend/data/verification/p3/evaluation.json` 和三个 `*-evaluation.xml` |
| 实际进程恢复 | 两次重启，13 条命令重放通过 | `backend/data/verification/p3/restart.json`；三个独立后端 PID，测试端口 8014 已停止 |
| 独立实现审查 | Pass，无未解决 Critical/Important | `changes/p3-business-agents/reviews/p3-independent-review.md`；审查者独立执行 26 项纯函数/假客户端测试 |
| 图表间距增量审查 | Pass，无 Critical/Important | `changes/p3-business-agents/reviews/p3-visual-review.md`；前端单测/构建再次通过 |
| 桌面/手机浏览器联合回归 | 36 passed，0 failed/skipped/flaky，213.01 秒 | `frontend/data/verification/p3/result.json`，含 P1/P2 回归与 P3 实际 HTTP 接口测试 |
| 截图检查 | 本次最终轮次 11 张 P3 截图逐张检查通过 | `frontend/data/verification/p3/browser/`；标题、加载完成、页面宽度、图表标签与局部滚动检查 |

39 是评测测试数，不是独立业务样本数。三个场景各有 6 个 development 和 6 个 acceptance 样本，共 36 个合成样本；证据包含 split、样本 ID、SHA256、provider 和规则/指标版本。评测中的模型为确定性 Mock/假客户端，不度量真实模型召回率或法律准确率。39 项已包含在后端 420 项中，不叠加为新的覆盖总数。

重启脚本创建并停止自己的 8014 进程，没有重置数据库；验证草稿、不可变历史、任务终态、报表发布和合同人工决定在两个进程边界后保持一致。同键重放不追加业务记录、版本或事件，`external_writes=false`、`paid_calls=0`。长合同在此验证中运行真实 DeepAgents 引擎及 Mock 模型。

最终浏览器运行于 2026-10-14 20:18:03 至 20:21:36（Asia/Shanghai），桌面 1440×960、手机 390×844。图表每对日期标签间距至少 2 px、非零柱真实高度和手机局部横向滚动均通过断言；手机测量的最小日期间距为 8.625 px。桌面使用内部内容区滚动，截图记录可见窗口，不作为全部合同风险全文的截图证据。本地工程判定为 Pass，B1-B6 完成。

## 使用与人工验收

预览：`http://127.0.0.1:5182`，后端健康检查：`http://127.0.0.1:8012/healthz`。保留现有 8001/5173 服务，验收预览使用独立端口。使用页面角色切换和三个业务导航进入工作台；合同创建人编辑草稿，指定复核人做最终决定。

人工步骤与结果表在 `docs/functional-test-guide.md` 的 T30-T37。结果表仍待人工填写，自动化通过不能冒充业务人员已验收。接口字段和权限见 `docs/api-contract.md`，逐项需求证据见 `changes/p3-business-agents/reviews/verification.md`。

报表使用上海时区，时间区间为 `[start,end)`，仅支持日粒度；周/月是日期模板。审批按创建时间进入区间，结果取查询时状态，不同审批版本分别计数。数值放在工具快照及图表中，人工和模型摘要都不能包含 Unicode 数字。

## 可复现命令

前端工作目录：`E:/OA AGENT SYSTEM/frontend`。

```powershell
npm test
npm run build
npx playwright test -c playwright.p3.config.ts
```

后端工作目录：`E:/OA AGENT SYSTEM/backend`。完整数据库测试会重置测试库，重跑前必须先停止使用该测试库的 8012 预览，然后串行执行；不得指向开发库 `oa_agent`。

```powershell
$env:ENVIRONMENT='test'
$env:DATABASE_URL='postgresql+asyncpg://oa:oa@localhost:5433/oa_agent_test'
$env:DATABASE_SYNC_URL='postgresql+psycopg://oa:oa@localhost:5433/oa_agent_test'
$env:CHECKPOINTER_URL='postgresql://oa:oa@localhost:5433/oa_agent_test'
$env:ALLOW_TEST_DATABASE_RESET='true'
$env:LLM_PROVIDER='mock'
$env:OA_PROVIDER='mock'
$env:AUTH_PROVIDER='mock'
& 'C:/Users/j/AppData/Local/Programs/Python/Python312/python.exe' -m pytest -q
```

独立证据脚本不重置数据，沿用上面的测试库和 Mock 配置，改用：

```powershell
$env:ALLOW_TEST_DATABASE_RESET='false'
& 'C:/Users/j/AppData/Local/Programs/Python/Python312/python.exe' scripts/verify_p3_evaluation.py
& 'C:/Users/j/AppData/Local/Programs/Python/Python312/python.exe' scripts/verify_p3_restart.py
```

## 生产待验收

真实企业身份、负责人目录和法务角色映射；真实业务数据与指标口径；组织及法律适用规则；真实模型质量、延迟、价格和成本；实际病毒扫描服务；人工验收 T30-T37。扫描服务未配置时文件保持 PENDING，不能送模型，粘贴文本仍可使用。

合同演示规则 `demo-1` 仅包含支付、违约、终止和争议四类检查。系统产物为辅助意见，不修改源合同、不签署、不外发。外部 OA/BI 同步、真实通知发送、OCR、扫描 PDF 和 DOCX 导入均在本阶段范围之外。

仓库当前无提交基线，因此不提供虚构 Git SHA 或完整变更 diff。`ssf` 及相关脚本缺失，按用户已授权的本地替代方式记录结果，不伪造 DP、执行 receipt、自动归档或生产批准；未合并/归档旧 P1/P2 变更，未提交或部署。
