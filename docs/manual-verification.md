# OA 智能体管理系统 MVP 手动验证步骤

本文档用于在本地验证当前 MVP 的主要功能和本次“知识库文档分割优化”。

> 正式化 B1～B7 已实现并完成主要自动化验收；B8.1/B8.2 与 B8.3 角色入口 E2E 已完成自动化验证，B8.4 部署演练和真实 OA 沙箱仍是上线前置条件。本文件中的 MVP 步骤不能代替后续批次验收。

### B3 FAQ/工单纠正验证

#### Docker 集成回归证据（2026-10-12）

Docker 已恢复，测试库为独立的 `oa_agent_test`（`5433`）。在 `backend` 目录执行：

```powershell
$env:ALLOW_TEST_DATABASE_RESET='true'
python -m pytest tests/migrations tests/api tests/graph -q
```

结果：`55 passed in 18.86s`。该结果覆盖通知失败暂停与对账、表单编辑响应丢失对账、工单草稿字段分层、消息幂等、工单确认门禁和图恢复；开发库未清空。

1. 在独立测试库执行 `python -m alembic upgrade head`，确认版本为 `0004`；不得在开发库执行清表或回滚。
2. 员工提问一个未命中或低置信度 FAQ，确认会话详情的 `handoff` 含队列项编号；相同会话重复扫描不得创建第二个 OPEN 队列项。
3. 员工提交工单描述后，在确认前读取 `GET /api/tickets/drafts/{thread_id}`，确认返回机器抽取字段和当前草稿。
4. 使用 `PATCH /api/tickets/drafts/{thread_id}` 修改 `priority`、`summary` 等允许字段；未知字段、非法优先级或空摘要必须返回 400，且不能创建正式工单。
5. 确认工单后再调用原确认流程，检查正式工单才产生；刷新/重启后草稿仍可从服务端读取。
6. 检查交接快照不包含 `token`、`api_key`、`password`、`secret` 等字段，消息上下文最多保留最近 20 条且单段有长度上限。

### B4 Task 4.1 服务端任务中心验证

1. 员工创建工单或请假会话后调用 `GET /api/tasks?page=1&page_size=20`，确认返回服务端任务列表，按更新时间倒序，包含 `task_type`、`business_status`、`next_action`、`responsibility` 和 `available_actions`。
2. 使用 `scene`、`status`、`updated_after`、`updated_before` 参数筛选，确认分页字段 `items/total/page/page_size` 稳定。
3. 使用审批人账号读取 `GET /api/tasks`，确认只看到自己当前活动审批节点负责的请假任务；二级节点未激活时不能提前看到或操作。
4. 使用任务发起人调用 `GET /api/tasks/{task_id}` 和 `POST /api/tasks/{task_id}/handoff`，确认详情可恢复且只创建一个人工交接项。
5. 暂停的请假任务调用 `POST /api/tasks/{task_id}/retry`，确认从安全检查点恢复；不支持重试的任务类型返回结构化 `42201`。

#### B4 Task 4.2 内置请假申请后端验证

1. 员工调用 POST /api/leaves 创建草稿，确认返回 application_id、业务号、状态 DRAFT 和版本 0。
2. 在 DRAFT 或 NEEDS_FIX 状态调用 PATCH /api/leaves/{application_id} 修改表单；其他状态必须拒绝修改。
3. 调用 POST /api/leaves/{application_id}/submit，确认返回结构化预检结果和规则版本；病假缺附件时为 NEEDS_FIX，且数据库不创建审批实例。
4. 补充附件后重新提交，确认生成新版本；GET /api/leaves/{application_id}/versions 返回不可覆盖的版本历史。
5. 使用其他租户/用户读取或修改申请，确认返回 40301 且不泄露字段。

本轮 Docker 集成已恢复，独立测试库回归已执行；开发库未清空。

#### B4 全量回归与真实浏览器证据（2026-10-13）

- Docker `oa-agent-db` 健康，后端集成回归使用独立 `oa_agent_test`：`150 passed`。
- 前端 Vitest：`16 passed`；`npm run build` 成功，仅有 Vite 大 chunk 提示。
- Edge + Playwright 真实页面验收：`12` 个场景通过，结果保存在 `data/verification/b4-browser/result.json`，无页面错误。覆盖草稿刷新、逐级审批/越级拒绝、余额不足、时间冲突、病假缺附件、附件上传/重扫/刷新、PENDING 禁止下载、驳回重提、审批人编辑后批准和移动端显示。
- 当前未配置 ClamAV，上传附件保持 `PENDING`；未通过扫描的附件不能下载或作为审批依据。浏览器验收连接 `oa_agent_test`，未清理开发库。

### B5 Task 5.1 工单运营后端验证（2026-10-13）

- 新增权威 `ticket_record`、版本化 `ticket_assignment_rule` 和确定性重复评分。
- 已确认工单按租户/申请人隔离；同摘要工单先返回重复候选，只有显式 `merge_ticket_id` 才合并，重复合并幂等。
- 无分派规则时工单保留为 `open`，不伪造队列或责任人，并返回 `NO_ASSIGNMENT_RULE`。
- 工单查询对员工、客服和管理员执行资源授权；普通审批人不能读取他人工单。
- 验证命令：`python -m pytest backend/tests/api backend/tests/migrations backend/tests/unit backend/tests/graph -q`，结果 `154 passed`。

### B1 工程底座验证（2026-10-12）

1. 从项目 `backend` 目录运行 `python -m alembic current`，应显示 `0005 (head)`。新环境先执行 `python -m alembic upgrade head`，重复运行应无副作用。
2. 正常启动后打开 `http://127.0.0.1:8001/healthz`，应显示 `status: ok`；迁移未执行时后端应拒绝启动，不得静默建表。
3. 直接运行 `python -m pytest tests/api -q`，应在任何清表前因缺少测试清理许可而失败。这是保护机制，不代表产品故障。
4. 使用独立的 `oa_agent_test` 数据库，再于单个 PowerShell 进程设置 `$env:ALLOW_TEST_DATABASE_RESET='true'`，运行 `python -m pytest tests/migrations tests/api tests/graph -q`。检查目标仅是测试库；运行后移除该环境变量。
5. `python -m pytest tests/unit -q` 无需数据库，实际用例数量以当前终端输出为准。
6. 通过管理员 Mock 用户调用配置查询，再在开发环境移除该用户的角色，应立即拒绝后续管理员操作；生产配置中 Mock 认证和未实现的真实 OA 均会拒绝启动。

备份文件保存在项目 `data/backups/`。此目录包含业务数据，禁止上传到公开代码仓库；仅具备授权的运维人员可保管和恢复。

### B2 逐级审批验证（后端更新后执行）

1. 确认后端进程已重启加载新代码且数据库迁移为 `0003`。使用浏览器访问 `http://127.0.0.1:8001/healthz`，并确认返回 JSON，而非其他项目的 HTML。8000 端口已被其他应用占用，当前项目改用 8001。
2. 用员工 `u_emp_001` 为 `LV-OK-001` 创建请假会话并发送“提交请假申请”，进入“请假任务”详情，应显示申请材料、预检、两级审批链和当前审批人李四。
3. 切换 `u_mgr_002` 尝试在一级未批准前操作，应无权操作。切换 `u_mgr_001`，批准当前级后确认仍为 `WAITING_HUMAN`、一级标为已批准、当前审批人改为王五，不能显示最终批准。
4. 切换 `u_mgr_002` 批准第二级，确认最终为 `APPROVED`、两条节点决定留存；用同一中断 ID/幂等键重复提交相同决定应回放首次结果，修改载荷应冲突，绝不能重复审批。
5. 在尚未审批的另一张测试单上选择“编辑后批准”，修改原因、填写编辑理由，确认重新预检且同一节点仍待处理；选择“驳回”时选择分类并填写文字原因，确认已驳回与分类均可追溯。
6. 用独立测试库模拟最后一级 OA 写入响应丢失：任务必须进入 `PAUSED`，核对接口 `/api/approvals/threads/{thread_id}/reconcile` 只能以原幂等键查询权威结果，不得再次发起审批写入；只有已确认的成功结果可以完成审批。
7. 先完成一条两级审批，再用同租户客服 `u_cs_001` 调用上述 `reconcile` 接口，应返回 403；仅有当前管理员或仍持有审批角色的最终审批人可以核对。不得通过核对接口绕过资源授权或推进编排检查点。
8. 只在独立测试库和临时 Mock OA 状态文件中，模拟一级审批后、二级审批前由 OA 修改同一请假单的原因，再尝试二级批准：必须返回 502、任务进入 `PAUSED`、权威审批写入及其幂等声明均不存在。先核对材料、重新预检，不要直接反复点击“安全重试”。无需修改开发库中的单据以验证此项；后端自动化测试已覆盖。
9. 没有可信预检表单快照的迁移前旧待办必须要求人工核对，不能凭原来的单号和审批人自动认领流程。已有但缺少中断 ID 的旧待办也不能自动补批。

注意：Mock 单号 `LV-OK-001` 在同一开发库中复用已有线程；要验证全新链路，需使用本人新提交的不同业务单号。不得为重测而清空开发数据库。

## 1. 验证范围

- 智能请假审批：预检、审批路由、人工批准/编辑批准/驳回、驳回后恢复。
- 智能客服/工单：FAQ 检索、来源展示、低置信度兜底、字段抽取、确认创建、工单查询、转人工。
- 平台能力：登录态复用、工具白名单、幂等、会话恢复、审计、策略开关、权限过滤。
- 知识库：Markdown 导入、权限标签、上下线、段落/标题切分、超长文本硬切分。

## 2. 环境和账号

确保以下地址可访问：

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5173 |
| 后端文档 | http://127.0.0.1:8001/docs |
| 健康检查 | http://127.0.0.1:8001/healthz |

Mock 账号：

| 用户 | 账号 ID | 用途 |
| --- | --- | --- |
| 张三 | `u_emp_001` | 员工、发起请假/问答/工单 |
| 李四 | `u_mgr_001` | 审批人 |
| 王五 | `u_mgr_002` | 二级审批人 |
| 赵六 | `u_cs_001` | 客服 |
| 管理员 | `u_admin_001` | 策略、知识库、审计 |

接口请求统一带登录头。PowerShell 示例：

```powershell
$base = "http://127.0.0.1:8001"
$emp = @{ Authorization = "Bearer mock:u_emp_001" }
$mgr = @{ Authorization = "Bearer mock:u_mgr_001" }
$admin = @{ Authorization = "Bearer mock:u_admin_001" }
```

所有成功接口通常返回 `{ code: "0", data: ... }`。浏览器操作优先使用前端页面；接口命令用于确认状态、错误码和审计记录。

## 3. 启动检查

1. 打开 `http://127.0.0.1:8001/healthz`，预期 HTTP `200`，返回 `status: ok`。
2. 打开 `http://localhost:5173`，预期进入“智能助手”页面。
3. 打开 `http://127.0.0.1:8001/docs`，确认可以看到 `/api/agent/threads`、`/api/approvals`、`/api/tickets`、`/api/admin/knowledge` 等接口。
4. 在前端“智能配置”页面切换为管理员，确认策略列表可以加载。

## 4. 请假审批主流程

### 4.1 正常预检和批准（AC-MVP-01、03）

1. 前端进入“智能助手”，角色切换为员工（张三）。
2. 场景选择“请假审批”。页面默认不填写单号，并提示请先在 OA 中提交完整请假单；此时“新建会话”按钮不可用。
3. 单号填写 `LV-OK-001`，点击“新建会话”。请假单号不存在时应直接提示错误，不能依靠一句自然语言创建完整请假表单。
4. 输入：`请帮我提交这个请假单`，点击发送。该消息只用于意图识别，预检材料来自 `LV-OK-001` 对应的 OA 表单。
5. 预期显示预检表，各检查项通过，状态进入等待人工审批，并显示审批链。
6. 点击“查看审批详情”，确认能看到业务单号、预检结果、审批人和当前中断。
7. 切换角色为审批人（李四），点击左侧“请假任务”返回同一个任务详情页。审批人可以查看审批链，但不能代替员工发送会话消息。
8. 在“审批链与决策”卡片中填写意见（例如 `同意`），点击“批准”。审批入口就在这个页面，不需要进入其他系统页面。
9. 第一级批准后预期仍为等待人工；切换王五批准第二级后才应变为已批准。页面显示两级节点、操作者与意见。
10. 回到审计中心，按会话 ID 或业务单号 `LV-OK-001` 查询，确认至少能看到预检、人工决定和业务写入事件。

### 4.2 预检异常边界（AC-MVP-02）

分别用员工账号创建请假会话并发送相同消息，验证以下单号：

| 单号 | 预期问题 | 预期结果 |
| --- | --- | --- |
| `LV-NOATT-001` | 病假缺附件 | 附件检查失败，不进入正式审批 |
| `LV-NOFIELD-001` | 缺少 reason | 必填字段检查失败，展示缺失字段 |
| `LV-NOBAL-001` | 余额不足 | 假期余额检查失败，不自动批准 |
| `LV-CONFLICT-001` | 时间非法/冲突 | 时间检查失败，不创建正式审批任务 |

也可以直接调用预检接口：

```powershell
$body = @{ business_id = "LV-NOATT-001"; retry = $false } | ConvertTo-Json
Invoke-RestMethod "$base/api/approvals/LV-NOATT-001/precheck" -Method Post -Headers $emp -ContentType "application/json" -Body $body
```

检查 `data.passed`、`data.status` 和 `data.precheck_result`，失败项必须包含原因或建议，不能只返回一个总失败状态。

### 4.3 驳回和重新处理（AC-MVP-04）

1. 使用 `LV-OK-001` 创建新的会话，推进到等待审批。
2. 使用审批人账号点击“驳回”，填写理由，例如 `请补充说明`。
3. 预期状态变为已驳回，并生成结构化驳回摘要/修改建议。
4. 员工重新进入该会话，确认原上下文和驳回理由仍存在。
5. B2 阶段保留原会话和驳回决定；员工修改原单并创建新版本、重新预检重提是 B4 的待开发功能，当前不能靠重新发送聊天内容完成。

### 4.4 编辑后批准和重复决定

1. 新建一个 `LV-OK-001` 会话并推进到人工审批。
2. 提交“编辑后批准”，可填写 `edited_data`（接口方式）或使用页面的编辑批准按钮。
3. 预期记录 `edit` 决定、更新 Mock OA 材料并重新预检；只有重新通过预检和逐级审批，才会产生最终批准写入。
4. 对同一个已处理的中断与幂等键提交相同决定，应回放首次结果而不重复执行审批；改动意见时应返回 409。

## 5. FAQ 知识问答

### 5.1 导入一份公开文档

1. 切换为管理员，进入“知识库”页面。
2. 导入以下内容：

```text
# 请假制度
年假需要提前一天提交申请。

## 病假材料
病假需要上传医院证明。
```

标题填写 `手动验证-请假制度`，权限标签留空，点击导入。
3. 预期列表出现该文档，状态为 `published`，版本为 `1`，权限显示“公开”。

### 5.2 命中并显示来源（AC-MVP-08）

1. 切换为员工，进入智能助手，场景选择“知识问答”。
2. 新建会话，提问：`年假需要提前多久提交？`
3. 预期返回回答、来源文档/切片位置和置信度，不应显示无来源的确定性结论。

### 5.3 未命中、低置信度和权限过滤（AC-MVP-09、10）

1. 管理员再导入一份权限标签为 `d_ops` 的文档，内容写入一条只有运营部可见的信息。
2. 员工（`d_rd`）提问该信息，预期不返回该文档内容，也不泄露文档存在性；问答场景只转人工核实，不生成工单草稿。
3. 员工提问一个知识库没有覆盖的问题，例如 `公司明年是否搬迁到上海？`，预期不猜测回答，应进入兜底路径。
4. 管理员将公开文档下线，回到员工会话再次提问，预期该文档不再参与检索。

## 6. 本次文档分割优化专项验证

目标是确认中文、英文、Markdown 和超长正文都能产生合理切片，并且单个切片不超过 500 个字符。

1. 管理员进入知识库，导入以下文本：

```text
# English heading
First sentence. Second sentence! Third sentence?

## 中文标题
第一段。第二段！第三段？
```

2. 预期导入成功，返回 `chunk_count` 大于 1 或按实际长度产生合理数量；标题不应和上一句拼接成 `sentence.##` 这样的文本。
3. 再导入一段超过 1,000 个字符、且中间没有任何标点的连续文本。
4. 预期导入成功，不报向量或数据库字段长度错误；每个切片长度都不超过 500。
5. 用这些文档中的关键词进行 FAQ 查询，确认能命中对应片段。
6. 如果需要精确核对切片数量，可查看后端日志/数据库 `knowledge_chunk` 表；导入接口至少应返回 `document_id` 和 `chunk_count`。

## 7. 工单闭环

### 7.1 抽取、确认、创建和查询（AC-MVP-11、13）

1. 员工进入智能助手，场景选择“工单办理”。
2. 新建会话，输入：`我的电脑无法开机，请帮我报修`。
3. 预期展示工单草稿，至少包含类别、优先级、问题摘要。
4. 点击“确认创建工单”。
5. 预期返回唯一工单号，状态进入已创建/处理中。
6. 点击工单号，或访问 `/ticket/<工单号>`，确认能看到工单字段和时间线。
7. 刷新页面或重新打开同一工单，确认状态和处理进度仍存在。

### 7.2 取消确认和转人工（AC-MVP-12）

1. 新建工单会话，输入 `账号无法登录`。
2. 在工单草稿阶段点击“取消”，确认不会创建工单。
3. 新建另一个会话，点击“转人工”。
4. 预期状态进入等待人工，人工上下文应包含已有对话、用户和已抽取字段。

### 7.3 工单创建门禁和幂等

接口直接创建工单时，验证以下情况：

- 不传 `thread_id`：预期 HTTP `422`。
- `idempotency_key` 不等于会话 ID：预期 HTTP `400`。
- 会话尚未完成 `confirm`：预期 HTTP `422`。
- 同一已确认会话重复创建：预期返回已有业务结果，不产生重复工单。

## 8. 权限、策略和降级

### 8.1 未认证和角色权限（AC-MVP-14、17）

```powershell
Invoke-WebRequest "$base/api/agent/threads" -Method Post -ContentType "application/json" -Body '{"scene":"faq"}'
```

预期未带 Authorization 时返回 HTTP `401`。

1. 使用员工账号访问管理员接口 `/api/admin/knowledge`、`/api/admin/agent-policies`、`/api/audit/events`。
2. 预期返回 HTTP `403`。
3. 管理员修改策略后，用管理员再次查询，确认 `enabled`、`thresholds`、`rule_version` 已保存。
4. 再次修改同一策略，确认审计中心出现配置变更事件，并包含操作者和变更时间。

### 8.2 场景关闭和恢复（AC-MVP-15）

1. 管理员在“智能配置”中关闭 `faq` 或 `ticket` 场景。
2. 对应用户新建该场景会话并发送消息。
3. 预期智能路径不阻断原业务，状态显示降级/关闭或转原 OA 路径。
4. 重新打开策略后重复测试，确认智能路径恢复。

### 8.3 B7 运维观测和降级控制（2026-10-13）

1. 使用管理员账号打开 `http://localhost:5173/operations`，确认运行指标卡片可加载；空数据时显示 0 或“暂无数据”，不应报 404。
2. 在 trace 输入框填写已知 `trace_id`，点击查询，确认节点时间线、工具错误和模型用量缺失标记可见；员工账号访问同一接口应返回 HTTP `403`。
3. 打开 `http://localhost:5173/degradation`，创建 `faq` 场景降级，分别选择新任务回退人工、在途任务暂停，填写原因并提交。
4. 使用员工账号创建 FAQ 会话并发送消息，确认新任务进入人工等待且不调用模型/工具；对已存在会话发送消息，确认在途任务进入暂停。
5. 管理员点击恢复，确认降级记录保留恢复时间和操作者，新的 FAQ 请求恢复正常路径。

自动化/服务冒烟证据（2026-10-13）：后端 `194 passed`，前端 `19 passed`，构建成功；`0015 (head)`；`/healthz` 返回 `status: ok`；管理员降级列表和运行指标接口返回 HTTP `200`。
### 8.4 B8 真实 OA、角色 E2E 与上线门槛（2026-10-13）

- B8.1 Provider 契约、认证头、只读重试、写入幂等/对账和能力探测定向测试通过；真实 OA 未配置时必须 fail-closed，不进入生产路径。
- B8.2 安全、注入、崩溃恢复和性能基线定向套件：`13 passed`。后端全量测试在显式 `ALLOW_TEST_DATABASE_RESET=true` 且目标为独立 `_test` 数据库时：`209 passed`；未设置清理许可时全量命令会被安全闸门拒绝，这是预期保护行为。
- B8.3 使用本机 Edge、复用现有前端服务运行五类演示角色菜单 E2E，连续两次均为 `5 passed`；前端组件测试 `19 passed`，`npm run build` 成功。该 E2E 只覆盖入口和角色菜单显隐，完整业务闭环仍需按下方手工步骤和真实数据验证。
- B8.4 `docker compose config --quiet` 通过，`oa-agent-db` 当前 healthy；本轮未执行 `down -v`、删卷、清库或覆盖开发数据。现有后端进程访问 `/api/readiness` 返回 `404`，需重启后端加载当前源码再复验；源码路由为 `/api/readiness`。Docker 构建此前因基础镜像 registry 异常未完成。

上线前必须补齐：

1. 提供并验收 `OA_BASE_URL`、`OA_API_KEY` 及 bridge 能力（`identity`、`leave_read`、`approval_write`）；在独立沙箱完成只读、写入、超时和响应丢失对账演练。
2. 在可控窗口重启后端，确认 `/api/readiness` 返回 `ready` 与三项必需能力，再执行部署文档和回滚手册中的备份/恢复演练。
3. 对员工、两级审批人、客服、管理员和审计/运维角色分别完成业务主流程验收，并保存 trace、截图和结果文件；未完成前不得标记 Batch 8 Exit。

## 9. 幂等、恢复和审计（AC-MVP-06、13、16）

### 9.1 消息幂等

使用同一个会话连续两次发送完全相同请求，并显式提供同一个 `idempotency_key`：

```powershell
$thread = Invoke-RestMethod "$base/api/agent/threads" -Method Post -Headers $emp -ContentType "application/json" -Body '{"scene":"faq"}'
$id = $thread.data.thread_id
$message = @{ content = "年假制度是什么？"; idempotency_key = "manual-message-001" } | ConvertTo-Json
Invoke-RestMethod "$base/api/agent/threads/$id/messages" -Method Post -Headers $emp -ContentType "application/json" -Body $message
Invoke-RestMethod "$base/api/agent/threads/$id/messages" -Method Post -Headers $emp -ContentType "application/json" -Body $message
```

预期第二次返回首次消息 ID 或等价的去重结果，不重复推进图、不重复写业务。

### 9.2 刷新/重启恢复

1. 创建一个会停在人工中断的请假或工单会话，记录会话 ID 和中断 ID。
2. 刷新前端；再访问会话详情。
3. 重启后端，再次访问同一个会话详情。
4. 预期状态、上下文、`current_interrupt_id` 和下一步动作保持一致，不能重复创建工单或审批。

### 9.3 审计查询

1. 管理员进入“审计中心”，按会话 ID、业务单号、动作分别查询。
2. 确认可以看到会话创建、意图路由、工具调用、预检、人工决定、业务写入、通知/异常等事件（以实际执行路径为准）。
3. 从接口响应记录一个 `trace_id`，再次按 `trace_id` 查询，预期只返回相关链路事件。

## 10. 结果记录表

建议每项填写“通过/失败”、实际结果、截图或 trace_id：

| 编号 | 验证项 | 结果 | 备注/trace_id |
| --- | --- | --- | --- |
| 1 | 启动和健康检查 |  |  |
| 2 | 请假正常预检和批准 |  |  |
| 3 | 请假异常预检 |  |  |
| 4 | 驳回与重新处理 |  |  |
| 5 | FAQ 命中与来源 |  |  |
| 6 | FAQ 权限过滤与低置信度 |  |  |
| 7 | 文档分割专项 |  |  |
| 8 | 工单确认创建与查询 |  |  |
| 9 | 转人工 |  |  |
| 10 | 幂等与恢复 |  |  |
| 11 | 策略开关/降级 |  |  |
| 12 | 审计查询 |  |  |

## 11. 判定标准

- 正向流程必须进入预期状态，并能在刷新/重启后恢复。
- 任何高影响写操作都必须先经过人工决定或确认。
- 权限不足、知识未命中、依赖异常时不得猜测、越权或自动通过。
- 重复请求不得创建重复审批、工单或通知。
- 发现问题时请同时记录：操作账号、接口路径、请求时间、HTTP 状态码、响应中的 `trace_id`、截图和复现步骤。
## B4 内置请假审批接入（2026-10-12）

1. 以员工身份创建年假申请并提交；预检通过后应返回 `SUBMITTED`，任务中心能看到对应任务。
2. 以 `u_mgr_001` 查看请假任务，应看到当前一级待办和 `approve/edit/reject`；`u_mgr_002` 此时不可见。
3. 调用 `POST /api/leaves/{application_id}/decision` 依次以 `u_mgr_001`、`u_mgr_002` 批准；任务应从 `WAITING_HUMAN` 进入 `APPROVED`，重复相同幂等键不得重复推进。
4. 创建病假且不上传附件；提交应为 `NEEDS_FIX`，数据库不应产生 `ApprovalInstance`。补齐附件后再次提交才进入审批。

## B5 Task 5.2 客服人工队列（2026-10-13）

1. 使用客服账号访问 `GET /api/support/queue`，确认只能看到同租户人工队列项，并返回交接快照和 SLA 状态投影。
2. 同时发送两个 `POST /api/support/queue/{queue_item_id}/accept` 请求；预期只有一个返回 `200` 并进入 `IN_PROGRESS`，另一个返回 `409`。
3. 使用客服账号调用 `POST /api/support/queue/{queue_item_id}/assign` 转派，再由目标客服调用 `POST /api/support/queue/{queue_item_id}/complete`。
4. 完成后确认人工项为 `RESOLVED`（或 `CLOSED`），关联 `TicketRecord` 状态已回写，`context.resolution` 包含处理结果。
5. 使用员工账号访问客服队列接口，预期返回 `403`。

## B5 Task 5.3 用户反馈与复盘（2026-10-13）

1. 将一个权威工单置为 `resolved` 或 `closed`，由工单发起人调用 `POST /api/tickets/{ticket_id}/feedback` 提交“已解决”反馈。
2. 使用同一 `idempotency_key` 重复提交，预期返回同一个反馈 ID，不新增反馈记录；使用相同幂等键但修改内容，预期返回 `409`。
3. 提交“仍需帮助”反馈，预期工单重开为 `open`，并创建原因码为 `NEGATIVE_FEEDBACK` 的人工复盘队列项。
4. 使用非工单发起人提交反馈，预期返回 `403`。

## B5 Task 5.4 客服工作台（2026-10-13）

1. 切换客服演示账号，确认左侧出现“客服队列”；员工账号不显示该菜单。
2. 打开客服队列，确认可看到人工交接摘要、原因码、SLA、责任人和关联工单。
3. 进入人工处理项，依次执行受理、转派、填写处理结果、完成并回写。
4. 打开关联工单工作台，确认状态、队列、责任人和时间线可见。

## B6 Task 6.1 文件解析与对象存储（2026-10-13）

1. 使用单元测试验证 Markdown 标题/段落、HTML 标题/正文和 PDF 页码均输出统一的 `text/page/section/paragraph` 定位结构。
2. 验证空文件、非法扩展名、超过 10 MiB 文件和非 UTF-8 文本分别返回稳定解析错误码：`empty_document`、`unsupported_type`、`file_too_large`、`invalid_encoding`。
3. 验证本地对象存储只能写入配置根目录，`../outside` 等路径逃逸被拒绝，并可按引用读回原始字节。
4. 当前 Task 6.1 只提供上传/预览契约和解析基础能力；知识来源、历史版本、发布/失效和检索切换属于 Task 6.2，尚未宣称完成。

## B6 Task 6.2 当前进度（2026-10-13）

已完成非破坏性基础：`knowledge_source`、`knowledge_version`、`knowledge_file` 表及迁移 `0010` 已就绪，开发库已升级到 `0010`。旧 `knowledge_document` 检索和文本导入仍保持兼容；在发布服务和按版本检索完成前，不应将 Task 6.2 或 Batch 6 宣称完成。

后端新增接口：

- `POST /api/admin/knowledge/versions`：创建解析就绪的草稿版本。
- `POST /api/admin/knowledge/versions/upload`：上传 Markdown/HTML/PDF 文件并保存原文件引用。
- `POST /api/admin/knowledge/versions/{id}/publish`：显式发布；同来源旧发布版本自动下线。

验证要点：同一来源版本号递增；历史版本保留；只有当前有效发布版本参与版本化检索；引用返回 `version_id`、版本号和页/章节定位；无版本化数据时回退旧文本知识检索。

策略版本治理入口：

- `/config/policies`：创建策略草稿、加载历史版本、发布和回滚。
- `POST /api/admin/agent-policy-versions`：创建不可变草稿。
- `POST /api/admin/agent-policy-versions/{id}/publish`：发布并下线同作用域旧版本。
- `POST /api/admin/agent-policy-versions/{id}/rollback`：基于历史版本生成新版本，不覆盖历史记录。
- `GET /api/admin/agent-policy-versions`：按场景查看版本时间线。

运行时状态：场景开关、运行时阈值、工具授权和催办/升级调度已优先读取已发布策略版本，并按 user > dept > tenant > global 解析；无命中时回退旧 `agent_policy`。完成最终 E2E 前，仍不将 Batch 6 宣称为最终完成。

## B6 Task 6.3/6.4 运行时接入回归（2026-10-13）

1. 创建并发布同一场景的 global 与 user 策略，确认 user 级策略覆盖 global；调用会话创建、运行时阈值或工具路径后检查行为及审计中的策略版本快照。
2. 清理测试库后执行策略版本测试与 HTTP 流程测试，工单确认中断使用 `approve` 应返回 `422`，不能因旧策略残留被降级为无中断。
3. 当前自动化证据：后端 `187 passed`，前端 `19 passed`，前端构建成功；仍需按本手册完成浏览器手工验证。

### 8.5 本地 Mock 验证结果（2026-10-13）

本地验证不依赖真实 OA 参数，且未清理开发数据库或删除 Docker 数据卷：

- Mock Provider `/api/readiness`：HTTP `200`，`ready: true`；`identity`、`leave_read`、`approval_write`、`ticket_write`、`notification` 均为 `true`。
- 后端全量测试：`209 passed`，仅有既存 `datetime.utcnow()` 弃用警告。
- 前端组件测试：`19 passed`；生产构建成功（存在既有大 chunk 警告）。
- Edge Playwright 角色入口 E2E：`5 passed`，覆盖员工、一级审批人、二级审批人、客服、管理员菜单显隐。结果文件：`frontend/data/verification/b8-browser/result.json`。
- Docker：`docker compose config --quiet` 通过；`oa-agent-db` healthy。

注意：当前运行中的旧后端进程访问 `/api/readiness` 仍可能返回 `404`；源码和 TestClient 已确认路由可用，需重启该进程后再做真实服务端复验。
