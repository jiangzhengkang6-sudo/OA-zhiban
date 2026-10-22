# OA 智能体管理系统 MVP - 接口契约

本文档固化 MVP 智能层对外接口契约、错误码与幂等规范，作为前后端与 OA 适配层的开发基线。

## 1. 通用约定

- 统一响应结构：

```json
{ "code": "0", "message": "ok", "trace_id": "...", "data": { } }
```

- 所有写接口支持幂等键；响应头统一回传 `X-Trace-Id`。
- 认证：MVP 复用 OA 登录态（Mock 阶段为 `Authorization: Bearer mock:<user_id>`）。

## 2. 接口列表

### 2.1 会话

| 接口 | 方法 | 请求核心字段 | 返回核心字段 |
| --- | --- | --- | --- |
| `/api/agent/threads` | POST | `scene`, `business_id` | `thread_id`, `status` |
| `/api/agent/threads/{id}/messages` | POST | `content`, `idempotency_key` | `message_id`, `status`, `trace_id`, `next_action` |
| `/api/agent/threads/{id}` | GET | 路径参数 | `state`, `next_action`, `business_id`, `current_interrupt_id`, `precheck`, `approval_route`, `answer`, `ticket`, `ticket_fields`, `error` |

### 2.2 中断恢复（HITL）

| 接口 | 方法 | 请求核心字段 | 返回核心字段 |
| --- | --- | --- | --- |
| `/api/agent/interrupts/{id}/resume` | POST | `action`, `comment`, `edited_data` | `status`, `next_action`, `trace_id` |

### 2.3 请假预检

| 接口 | 方法 | 请求核心字段 | 返回核心字段 |
| --- | --- | --- | --- |
| `/api/approvals/{business_id}/precheck` | POST | `business_id`, `retry` | `precheck_result`, `passed`, `status`, `rule_version` |

### 2.4 工单

| 接口 | 方法 | 请求核心字段 | 返回核心字段 |
| --- | --- | --- | --- |
| `/api/tickets` | POST | `category`, `priority`, `summary`, `context`, `idempotency_key`, `thread_id` | `ticket_id`, `status` |
| `/api/tickets/{ticket_id}` | GET | 路径参数 | `ticket`, `timeline` |

### 2.5 审计

| 接口 | 方法 | 请求核心字段 | 返回核心字段 |
| --- | --- | --- | --- |
| `/api/audit/events` | GET | `trace_id`, `thread_id`, `business_id`, `actor_id`, `action`, `start_time`, `end_time`, `page`, `page_size` | 分页事件列表 |

### 2.6 管理：策略与知识

| 接口 | 方法 | 请求核心字段 | 返回核心字段 |
| --- | --- | --- | --- |
| `/api/admin/agent-policies` | GET/PUT | `scene`, `scope_type`, `scope_value`, `enabled`, `thresholds`, `rule_version` | 策略列表/单条 |
| `/api/admin/knowledge` | GET/POST | `title`, `content`, `format`, `permission_tags`, `owner_id` | 文档列表/导入结果 |
| `/api/admin/knowledge/{id}/status` | PUT | `status` | 更新后文档 |

## 3. 错误码

| 错误码 | 含义 | HTTP |
| --- | --- | --- |
| 0 | 成功 | 200 |
| 10001 | 参数校验错误 | 400 |
| 40101 | 未认证 | 401 |
| 40301 | 无权限 | 403 |
| 40302 | 工具白名单拒绝 | 403 |
| 40401 | 资源不存在 | 404 |
| 40402 | 中断不存在 | 404 |
| 40901 | 幂等冲突/重复提交 | 409 |
| 40902 | 中断已处理 | 409 |
| 42201 | 业务状态不允许 | 422 |
| 50201 | OA 依赖失败（暂停） | 502 |
| 50001 | 内部错误 | 500 |
| 50301 | 智能层降级 | 503 |

## 4. 幂等规范

- 写工具（`create_or_update_oa_approval` / `create_or_merge_ticket`）幂等键约定：
  - 审批落库：`idempotency_key = business_id`；
  - 工单创建：`idempotency_key = thread_id`（每会话一工单）。
- 重复提交相同幂等键时，返回既有结果，不重复执行业务写。
- 消息接口使用 `idempotency_key` 去重；重复请求返回首次消息 ID，不再次推进图或写入消息。
- 工单直接写接口必须提供已完成 `confirm` 的 `thread_id`，且 `idempotency_key` 必须等于该会话 ID；不能绕过会话确认门。
- 服务重启后 LangGraph 从 Checkpointer 恢复断点，配合幂等键保证不重复写。

## 5. OAAdapter 契约

OA 是权威系统，智能层通过 `OAAdapter` 协议访问（详见 `backend/app/adapters/oa_adapter.py`）：

```python
class OAAdapter(Protocol):
    def get_user_context(self, user_id) -> UserContext: ...
    def get_leave_case(self, business_id) -> LeaveCase: ...
    def get_leave_balance(self, user_id, leave_type) -> Balance: ...
    def get_approval_route(self, user_id, case) -> ApprovalRoute: ...
    def create_or_update_approval(self, command) -> OAResult: ...
    def create_or_merge_ticket(self, command) -> TicketResult: ...
    def notify(self, command) -> NotificationResult: ...
```

get_* 只读；create_* / notify 为写，必须 HITL + 幂等。

## 6. P2 文档与邮件

两类工作台均按实时身份、租户及发起人限定访问；管理员仅能查看其他发起人的任务摘要。确认保存平台内记录，响应 `external_writes=false`。

| 接口 | 方法 | 核心字段或行为 |
| --- | --- | --- |
| `/api/documents/templates` | GET | 静态版本化公文、通知、报告、总结模板 |
| `/api/documents` | POST/GET | 创建输入及来源快照；分页发起人列表 |
| `/api/documents/{id}` | GET | 模板、来源、当前草稿、检查、动作及确认记录 |
| `/api/documents/{id}/generate` | POST | 首次生成，`idempotency_key`、`expected_version` |
| `/api/emails` | POST/GET | 主题、发件人、收件人、正文、外部联系人标记、附件名称/敏感标记；分页列表 |
| `/api/emails/{id}` | GET | 原文来源、分类/优先级/摘要/待办/回复、检查、二次确认要求 |
| `/api/emails/{id}/analyze` | POST | 首次分析，`idempotency_key`、`expected_version` |
| `/api/{documents\|emails}/{id}/draft` | PATCH | 保存新版本，`draft`、当前 `expected_version`、`idempotency_key` |
| `/api/{documents\|emails}/{id}/versions` | GET | 不可变历史版本 |
| `/api/{documents\|emails}/{id}/retry` | POST | 仅 PAUSED；新的显式尝试键及当前版本 |
| `/api/{documents\|emails}/{id}/decisions` | POST | `action=confirm/reject/regenerate`、版本、键；拒绝要求 `reason` |

确认要求 `metadata_confirmed`，存在警告时要求 `warnings_acknowledged`；邮件外部联系人或敏感附件额外要求 `secondary_confirmed`。文档决策不接受邮件专属字段。未保存修改必须先保存新版本。过期版本返回 409；终态 fresh 命令返回 422；模板检查错误阻止确认。

模型超时、输出结构/来源错误返回持久化的 PAUSED 记录及脱敏错误/trace_id，HTTP 200 表示命令已记录，不代表草稿生成成功。业务持久化失败回滚；同键同负载重放返回首次响应，不再生成版本，当前身份和文档来源访问仍需有效。不同负载复用键返回 409。通用 messages/resume/handoff/retry 不可绕过专用工作台。

## 7. P3 工作任务、报表与合同

创建携带 `idempotency_key`；修改/决定携带当前 `expected_version` 与键。服务端刷新身份、租户及资源权限。HTTP 200 的生成响应需检查业务 `status/error`，PAUSED 不表示生成成功。字段约束以三份后端 schema 和 OpenAPI 为准。

| 接口 | 方法 | 行为与核心字段 |
| --- | --- | --- |
| `/api/work-tasks/batches` | POST/GET | 创建/列出候选批次；`source_type=meeting/ticket/approval`、`source_id`，会议可指定 `source_version` |
| `/api/work-tasks/batches/{id}` | GET | 当前授权来源、候选、版本和动作 |
| `/api/work-tasks/batches/{id}/extract` | POST | 提取或显式重试，不创建任务 |
| `/api/work-tasks/batches/{id}/draft` | PATCH | `draft.candidates`；保存新版本，负责人/带时区期限由人补充 |
| `/api/work-tasks/batches/{id}/versions` | GET | 有权限来源下的不可变历史 |
| `/api/work-tasks/batches/{id}/decisions` | POST | `action=confirm/reject`、`selected_candidate_ids`、`metadata_confirmed`、`risk_acknowledged`、`reason`；确认原子创建所选任务 |
| `/api/work-tasks`、`/api/work-tasks/{id}` | GET | 创建人/当前负责人范围；列表分页 |
| `/api/work-tasks/{id}` | PATCH | 标题、负责人、期限、优先级、敏感标记与核对/风险确认 |
| `/api/work-tasks/{id}/commands` | POST | `action=start/progress/complete/cancel/archive`、进度/备注；角色和状态机约束 |
| `/api/work-tasks/{id}/events` | GET | 业务事件历史 |
| `/api/work-tasks/notifications`、`/api/work-tasks/notifications/{id}/read` | GET、POST | 私有内部提醒列表/标记已读，无 OA/邮件发送 |
| `/api/reports/metrics` | GET | 三个固定版本化指标与统计口径 |
| `/api/reports` | POST/GET | `subject`、`plan`；创建计划/本人报告分页 |
| `/api/reports/{id}`、`/api/reports/{id}/versions` | GET | 当前范围有效才返回报告及历史 |
| `/api/reports/{id}/approve-plan` | POST | `plan_confirmed=true`；批准后执行只读查询并生成摘要 |
| `/api/reports/{id}/retry` | POST | 查询/模型故障恢复；合法缓存快照可复用 |
| `/api/reports/{id}/draft` | PATCH | `draft.summary/metric_refs/possible_causes`；只追加摘要版本，不修改数据快照 |
| `/api/reports/{id}/publish` | POST | `definitions_confirmed`、`causes_acknowledged`；平台内发布、终态只读 |
| `/api/contracts` | POST/GET | `title/reviewer_id/text`；创建私有原文及列表 |
| `/api/contracts/uploads` | POST multipart | `title/reviewer_id/idempotency_key/file`；TXT/文本 PDF，扫描门 |
| `/api/contracts/{id}`、`/api/contracts/{id}/versions` | GET | 同租户创建人/指定复核人可见 |
| `/api/contracts/{id}/sources/{source_id}` | GET | 私有页码、段落、偏移、引文 |
| `/api/contracts/{id}/commands` | POST | `action=review/retry/save/confirm/reject/rescan`；保存用 `summary`，复核用 `comment/dispositions` |

报表计划仅接受三个登记指标、`grain=day`、`scope=own/tenant` 与最长 366 天范围，tenant 范围仍受角色授权。审批/工单/任务均按 `created_at` 计入区间，审批不同版本分别计数，状态取查询时值。日期字符串以 Asia/Shanghai 午夜解析，区间为 `[start,end)`。周/月模板只预置日期。摘要和候选原因只能写定性文字，含数字或无效指标引用拒绝；数值展示由工具快照承担。不存在报表通用 commands/reject 接口。

合同确认只允许当前具备 approver/admin 角色的指定复核人，必须逐风险填写处理意见与最终意见；风险动作 `accepted/mitigated/needs_revision`。短文本使用确定性演示规则；超过 8,000 字符实际运行 DeepAgents。文件扫描未配置时保持 PENDING，不进入模型。公共任务/线程投影脱敏，通用 messages/resume/handoff/retry 不允许替代 P3 专用命令。

重复命令重放重新检查当前权限。任务命令返回原业务结果，同时刷新来源可见性、来源引用和可用动作；不得将旧动作当作当前授权。报表及合同重放返回已保存结果且不追加版本/决定。持久化失败向上传播并回滚，合同先前已保存节点可在租约失效后用新显式重试键恢复。
