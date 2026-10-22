# M3 内置能力验收矩阵

更新：2026-10-20。对照 `specs/formal-business.md` M3-01/02/09/10。实施者逐项核对，非独立审查；不虚构 Git SHA 或 ssf 收据。最新联合运行结果见 B5 报告。

## 十三项核心和两个辅助读取

下表测试文件均在 `backend/tests/contracts/`。`test_builtin_capability_matrix.py` 的参数化测试对全部 15 个方法注入已禁用的缓存身份，要求 401 且无领域命令；另一测试严格比较公布能力、异步协议和实际方法，避免漏项。

| 编号 | 方法 | 正常、异常和恢复证据 |
| --- | --- | --- |
| C01 | capabilities | `test_builtin_gateway.py::test_builtin_gateway_exposes_capabilities_without_legacy_adapter`；精确方法集合由 capability_matrix 验证，返回提供者及确认绑定信息，无密钥 |
| C02 | get_user_context | gateway 中本人无需请假权限、跨租户拒绝、不能借请假权限读取他人身份三个测试；组织读取单独授权 |
| C03 | get_leave_case | capability_matrix 的 detail/balance 只读测试和其他本人/他租户拒绝测试；不回退旧 LeaveApplication |
| C04 | get_leave_balance | leave_gateway 的跨年额度测试；capability_matrix 检查缺假种 404、其他本人/他租户拒绝及无写入 |
| C05 | get_approval_route | leave_gateway 的已提交模板版本冻结测试；capability_matrix 的其他本人/跨租户拒绝 |
| C06 | create_or_update_approval | leave_gateway 的提交、当前审批席位决定、缺确认拒绝、过期确认、提交结果重放；capability_matrix 的同键异载荷拒绝 |
| C07 | get_approval_result | leave_gateway 的只读结果、当前资源撤权、审批决定对账；capability_matrix 的缺结果返回 None 且不补写 |
| C08 | edit_leave_case | leave_gateway 的修改入参保持、确认原子性、缺失/过期确认；capability_matrix 的同键异载荷拒绝和同载荷重放 |
| C09 | get_leave_edit_result | leave_gateway 的当前资源撤权；capability_matrix 的缺结果只读；修改确认测试核对已提交结果 |
| C10 | create_or_merge_ticket | ticket_gateway 的提交/恢复/撤权；capability_matrix 的载荷变更冲突；正式图测试覆盖重复候选、新建/合并、目标改版重新确认 |
| C11 | get_ticket_result | ticket_gateway 的原业务键恢复、单次写入和撤权；capability_matrix 的其他操作者不可读取；不存在结果不重新写入 |
| C12 | notify | notification_gateway 的持久意图、同键重放、源业务权限、严格字段、trace 恢复；capability_matrix 的异载荷冲突 |
| C13 | get_notification_result | notification_gateway 的渠道实际状态、当前权限、来源撤权及旧无可信来源 503；capability_matrix 的缺结果只读 |
| A01 | get_ticket_status | ticket_gateway 正常结果状态；capability_matrix 的其他操作者访问拒绝；读取正式工单，不混用 legacy |
| A02 | get_field_dict | leave_gateway 的已发布模板字段及版本、无模板读取范围返回空；全方法禁用身份测试 |

## 确认、事务和图恢复

`integration/test_m3_leave_graph.py`、`test_m3_ticket_graph.py` 验证本人确认、变更后重新确认、禁用/调岗/撤权、伪造 checkpoint 拒绝、同键并发和审计失败整体回滚。工单重复选择包含合并目标及 revision；请假不采信模型给出的审批路线。

`test_m3_ticket_graph.py::test_formal_ticket_merge_review_and_committed_result_survive_runtime_restarts` 及两类正式图的 HTTP/PostgreSQL 重启测试关闭旧 GraphRuntime 后重新构建，读取原键对账。`recovery/test_m3_replay.py` 另用新 session 验证业务已提交而图未保存时无重复工单。FAQ 的真实登录、PostgreSQL 重启和策略/阈值/来源复核见 `test_m3_faq_graph.py`。

`test_builtin_notification_gateway.py` 和 `integration/test_oa_notification_processes.py` 区分通知意图、站内入箱、SMTP 受理及 UNKNOWN；结果查询不会补发通知。SMTP 只在批准的本机捕获环境测试，结果不代表生产送达。

## 验证边界

全部 15 项的禁用身份检查不等于每项都有独立 HTTP 端点或外桥生产集成。builtin 使用携带 actor/session/trace/confirmation 的异步内桥；Mock/real 的兼容另由 provider/HTTP 契约测试验证。无能力拒绝可以证明边界，不能替代本表必须能力的成功路径。
