# M3 六场景来源与复用验收矩阵

更新：2026-10-20。对应 M3-11/12。路径均相对 `backend/tests/`；按实际入口列证据，不把未实现的文件导出当作测试通过。当前联合结果见 B5 报告。

| 场景 | 实际权属与来源 | 当前范围、缓存、重放及异步边界证据 |
| --- | --- | --- |
| 文档 | 本人或显式部门 document 权限；正式知识绑定和已发布版本 | `integration/test_m3_document_sources.py`：检索前过滤、知识权限、绑定撤销后的详情/版本/创建与生成重放/线程、正文篡改拒绝、生成期间来源变更；`test_m3_derived_authority.py`：所有者调岗后的列表/详情/版本，生成/重试/重新生成期间调岗的成功和异常分支 |
| 邮件 | 本人或显式部门 email 权限；本地输入、分析与草稿，未连接外部邮箱发送 | `test_m3_derived_authority.py`：当前部门列表/详情/版本，分析/重试/重新分析期间调岗的成功和异常分支；共享读写边界由 email_service 的统一权限入口控制 |
| 会议 | 本人或显式部门 meeting 权限；本地输入、解析、草稿和人工确认 | `test_m3_derived_authority.py`：详情/列表调岗、解析/重试/重新解析期间调岗、图执行后的保存/确认/驳回复核；任务仅可引用已确认的精确会议版本 |
| 工作任务 | 批次本人私有；具体任务限创建人或执行人；来源为当前可读正式工单、已结束请假/报销或已确认会议 | `test_m3_formal_sources.py`：正式工单/请假、版本和撤权；`test_m3_derived_authority.py`：报销来源、来源撤权停止后台提醒；`test_m3_scene_reuse.py`：版本/创建/抽取/确认重放复核，独立任务保留但隐藏失权来源；`test_m3_department_reports.py`：部门报表权限不扩大任务参与范围 |
| 报表 | 报表 read/write 权限与所选来源范围交集；仅本人及有明确授权的部门范围，正式租户全域拒绝 | `test_m3_formal_sources.py`：正式工单/类型化审批，不读 Mock；`test_m3_derived_authority.py`、`test_m3_scene_reuse.py`：来源撤权、调岗、空快照、图返回后复核及缓存重放；`test_m3_department_reports.py`：部门权限与每类来源交集、跨部门/租户排除、源所有者调岗、真实登录 HTTP 和受限任务统计 |
| 合同 | 本人及指定审核人私有；显式 contract 权限，不借管理员角色或同部门扩大 | `test_m3_contract_authority.py`：正常审核人、只读审核人、禁用、同部门及跨租户拒绝；`test_m3_scene_reuse.py`：详情/版本/原文片段/创建与命令重放撤权，图节点返回后复核且不持久化失权结果 |

## 预览与导出入口

六场景的界面预览消费详情、版本、解析或原文片段接口，适用上表服务权限。当前 documents/emails/meetings/work-tasks/reports/contracts 路由均没有独立文件导出或下载接口；不声明 PDF/Word/Excel 文件导出已经实现或通过。若后续增加文件导出，须另测创建、取件和文件完整性全过程的最新权限。

实际存在的审计文件导出单独验证：`integration/test_m3_audit_authority.py`、`api/test_audit_export.py` 覆盖筛选、租户/本人/部门、引用来源撤权、创建者、过期、文件哈希、详情和下载；审计导出不能替代六场景导出证据。知识上传/解析预览属于知识管理；报销发票下载属于正式附件授权，均不等于派生场景导出。

## 后台与人工路径

正式审批催办和通知分发不依赖 AI 开关，证据为 `integration/test_m3_ai_disabled.py`、`unit/test_oa_scheduler_dispatch.py` 和 `integration/test_oa_notification_processes.py`。已修复主循环只在 Mock 身份下调用工作任务扫描的问题：`test_m3_derived_authority.py::test_builtin_scheduler_reminds_existing_tasks_when_ai_is_disabled` 使用实际主循环及数据库，验证关闭 AI 后仍产生逾期/升级提醒和重复扫描去重。收件人/创建者禁用、源所有者调岗及来源撤权由同文件后台测试验证。

文档、邮件、会议、报表、合同没有自动向外部系统提交的后台派生任务；模型生成结果通过人工确认/审核接口推进。模型输出和文档内容不授予业务权限。独立任务的来源失权会屏蔽来源正文，不自动删除已产生的本人任务。
