# P3 交付验证记录

日期：2026-10-14。判定范围：执行契约定义的本地 Mock 工程闭环。判定：Pass，B1-B6 本地工程完成；生产准入及业务人工验收仍待完成。

## 验证维度

| 维度 | 结果 | 依据 |
| --- | --- | --- |
| Completeness | Pass（本地范围） | B1-B6 完成；T1-T5/R1-R5/C1-C5 逐项实现与测试映射如下，交付文档及预览齐备 |
| Correctness | Pass（本地范围） | 420 后端、58 前端、构建、39 独立评测、两次重启/13 重放、独立审查；最终浏览器 36 passed 与 11 张 P3 截图检查通过 |
| Coherence | Pass（本地范围） | 设计、实际 API、0019-0022 迁移、DeepAgents、时区及定性摘要约束已对齐 |

完整运行命令、环境、已有警告、预览和生产待验收项集中在 `docs/p3-acceptance.md`。后端完整回归和前端测试/构建的证据为本次开发实际终端输出；未保存的全量日志不冒充磁盘证据。

## 需求追踪

以下实现路径相对仓库根，测试路径在 `backend/tests/` 下；UI 测试在 `frontend/src/tests/` 下。规格正文以 `specs/work-task.md`、`specs/report.md`、`specs/contract.md` 为准。

| 需求 | 实现证据 | 测试与交付证据 |
| --- | --- | --- |
| T1 授权来源 | services/work_task_service.py、work_task_generator.py、tools/work_task_tools.py | api/test_work_task_http.py：来源类型、证据、生成期间撤权、历史/重放撤权；unit/test_work_task_generator.py；独立工作任务评测 |
| T2 人工创建与风险 | work_task_service.py、models/work_task_batch.py、work_task_draft_version.py、work_task.py | test_work_task_http.py：有效负责人、风险确认、跨批唯一、并发重复确认；work-task-workbench.test.ts |
| T3 权限与状态机 | work_task_service.py、models/work_task_event.py、frontend/src/views/WorkTaskView.vue | test_work_task_http.py：版本冲突、负责人/改派、终态；浏览器创建→开始→完成→归档 |
| T4 私有提醒 | work_task_scheduler.py、models/work_task_notification.py、0019/0022 迁移 | test_work_task_http.py：两阶段去重、终态保护、权限/场景、211 行和 2000 不可用接收者公平轮转 |
| T5 事务恢复隔离 | graph/work_task_graph.py、work_task_service.py、共享 task/thread/interrupt/audit 边界 | test_work_task_http.py：失败暂停、审计失败回滚、usage；api/test_p3_boundaries.py、test_p3_audit_isolation.py、graph/test_p3_routing.py；restart.json |
| R1 指标与权限范围 | services/report_metrics.py、report_query.py、tools/report_tools.py | api/test_report_http.py：精确数字、空数据、租户/本人范围、改派与角色撤销；test_report_rules.py、独立报表评测 |
| R2 计划与只读限制 | schemas/report.py、report_service.py、report_query.py | test_report_http.py：登记指标/SQL 拒绝、真实 PostgreSQL READ ONLY、计划批准及范围撤销；report-workbench.test.ts |
| R3 数字与异常候选 | report_generator.py、report_metrics.py、models/report_record.py、MetricChart.vue | test_report_rules.py：交换数值、未知引用、Unicode 数字拒绝；test_report_http.py：精确快照、无对比、非法模型暂停；浏览器真实柱状图 |
| R4 不可变审阅发布 | report_service.py、models/report_record.py、frontend/src/views/ReportView.vue | test_report_http.py：不可变发布、版本冲突/历史；report-workbench.test.ts：未保存/确认门；浏览器保存→发布→刷新终态 |
| R5 故障恢复隔离 | graph/report_graph.py、report_service.py、共享权限/通用入口边界 | test_report_http.py：查询失败、模型失败复用快照、通用 chat/resume 拒绝；test_p3_boundaries.py、unit/test_p3_llm_budget.py；restart.json |
| C1 私有解析门 | contract_parser.py、models/contract_source.py、contract_record.py、api/routers/contracts.py | unit/test_contract_parser.py：文本/TXT/PDF、加密/损坏/扫描/超限；api/test_contract_http.py：PENDING 不生成及私有输入 |
| C2 四节点与 DeepAgents | graph/contract_graph.py、services/contract_rules.py、contract_deepagents.py；requirements.txt | unit/test_contract_deepagents.py：真实引擎/Mock、计划和全部分块、禁用工具/超限；独立合同评测；restart.json 长文真实引擎 |
| C3 可校验证据/指定复核人 | contract_parser.py、contract_service.py、schemas/contract.py | test_contract_http.py：证据、风险完整性、复核人角色撤销；合同评测；contract-workbench.test.ts 与浏览器角色切换 |
| C4 人工决定与不可变版本 | contract_service.py、models/contract_review_version.py、frontend/src/views/ContractView.vue | test_contract_http.py：版本冲突、风险逐项处理、决定账本；浏览器保存/版本比较/指定复核/确认终态；restart.json 重放 |
| C5 私有恢复/隔离 | contract_service.py、contract_graph.py、共享 thread/task/interrupt/audit 边界 | test_contract_http.py：私有读/历史/重放、通用恢复拒绝、数据库失败与失效运行恢复；unit/test_contract_recovery.py：固定规则快照；test_p3_boundaries.py、test_p3_audit_isolation.py；restart.json |

表中服务/模型/图路径均位于 `backend/app/`，迁移位于 `backend/migrations/versions/`；文件存在和对应行为已核对。迁移 `tests/migrations/test_p3_agents.py` 验证从 P2 升级到 0022、空 schema 往返和非空降级拒绝。共享场景开关测试按三个场景分别验证关闭/降级不影响 P1/P2 和其余 P3 场景。

## 可持久读取的结果

- `backend/data/verification/p3/evaluation.json`：三个场景 13/14/12 项，合计 39 passed；36 合成样本，split/hash/provider/规则版本；对应三个 JUnit XML。
- `backend/data/verification/p3/restart.json`：Pass，PID 38220/38828/6652，两次真实重启，13 命令重放，测试库 oa_agent_test；付费调用 0，外部写入 false；8014 进程已停止。
- `reviews/p3-independent-review.md`：独立审查 Pass；六项重要问题修复后复审通过、候选身份去重问题已修复；独立执行 26 项纯函数/假客户端测试。审查者未独立执行数据库测试，该部分由上述完整回归验证。
- `reviews/p3-visual-review.md`：图表间距与浏览器截图/几何断言增量独立审查 Pass，无 Critical/Important；没有将父线程浏览器结果冒充审查者执行结果。
- `frontend/data/verification/p3/result.json` 和 `browser/`：本次最终浏览器统计和实际截图，包含桌面 1440×960、手机 390×844；具体最终统计见下文收尾结果。

## 失败调查与修复

独立审查推动的产品修复包括：报表改用定性摘要防止交换数字；持久化异常不误分类为合同模型故障；内部提醒持久轮转防止候选饥饿；恢复固定规则快照；P3 审计按租户过滤；真实报表调用传递输出 token 上限及 provider usage；候选身份由服务端确定。相关回归和复审已完成。

浏览器初轮失败经 trace/接口调查确认来自验收脚本：来源 fixture 触发既有工单相似去重，改用真实创建并确认的会议；Element Plus 选择器改为对应 combobox 的键盘展开；确认任务接口返回后历史刷新尚未结束，过早导航受 busy 保护，改为等待任务列表按钮可用后点击。两次完整调查轮次各为 34 passed/2 failed；随后完整轮次为 36 passed。

截图检查发现标题先显示但详情仍加载导致骨架屏、桌面内部内容区滚动造成标题裁切；脚本新增 skeleton/loading 等待和标题可见断言。首次截图修正完整运行仍为 34 passed/2 failed：失败均为桌面标题可见性断言，根因是脚本用了不存在的 `.content`，实际滚动容器为 App.vue 的 `.app-main`。已按源码和失败截图定位后改用实际选择器，保留原断言重跑 36 passed。手机报表额外验证横向滚动及非零柱。

该轮截图进一步确认手机日期标签重叠，真实浏览器测量 14 个标签宽 27.796875 px、最小相邻间距 -1.375 px。产品图表最小宽度按日桶从 26 px 改为 36 px，继续使用局部横向滚动；浏览器增加每对相邻标签至少 2 px 间距断言。修正后真实手机测量最小间距 8.625 px，页面无横向溢出。重新执行前端单测 58 passed/13 文件、构建 exit 0，增量视觉代码审查 Pass；最终完整浏览器结果见收尾记录。没有后端变更，不为图表间距重置数据库或重复后端全套测试。

## 界限与收尾

最终完整浏览器命令 `npx playwright test -c playwright.p3.config.ts` 于 2026-10-14 20:18:03 至 20:21:36（Asia/Shanghai）执行，exit 0，耗时 213.010858 秒。`result.json` 的 stats 为 expected=36、unexpected=0、skipped=0、flaky=0，errors 为空。包含桌面 1440×960 和手机 390×844 的 P1/P2 回归与三个 P3 实际 HTTP 业务闭环。

最终轮次 11 张 P3 截图已逐张打开检查：两种视口各有任务候选/归档、报表审阅、合同审阅/确认共 10 张，另有手机图表滚至最右的截图。标题可见、无加载骨架和页面横向溢出；日期标签不重叠，最后日期的非零柱可见。相邻标签至少 2 px、真实柱高度和手机滚动位置由浏览器几何断言验证。桌面截图为内部滚动容器的可见窗口，不声称已展示全部合同风险全文。

B1-B6 本地工程交付完成，用户人工验收表和生产事项保持待验收。预览前端 5182、后端 8012 保留；重启验证用 8014 已停止。

本地工程结果不扩大范围到付费模型、真实邮件/通知、外部 OA/BI 写入或签署。真实身份、数据、模型、成本、扫描、组织法务规则以及人工 T30-T37 结果仍待验收。既有 bundle 大小和 Vue 测试图标组件 warning 不阻止本次构建/测试通过，不把 warning 隐去。

无有效 Git 提交基线；SSF 工具缺失，按已授权本地替代流程记录，不编造 SHA、DP 或 receipt。本次不归档旧变更、不合并主规格、不提交/部署。人工测试表未填写，不写成已验收。
