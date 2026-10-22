# M3 开发交接检查点

日期：2026-10-19。本轮按交接要求保存当前状态并停止实施，不修复新发现问题、不启动新一轮测试。B5、B7 及 M3 均未完成；B6 仍只有局部证据。执行契约和人工串行、实施者复核替代方式的既有批准保留，无独立审查或机器收据。

## 已保存的实现

- 正式 FAQ 在异步调用前后校验身份、策略、阈值、工具及来源；文档在向量截断前过滤绑定，并在详情、历史、重放、线程读取和生成后复核来源。
- `backend/tests/m3_http_support.py` 使用真实 CSRF、密码登录、JWT 和认证中间件；仅将会话工厂指向批准的测试库，退出时恢复依赖覆盖。
- `backend/tests/integration/test_m3_audit_authority.py` 有 16 项审计用例，含来源撤销、业务权限、筛选/序列化以及导出所有者、范围、业务权限和过期复核。
- 新增 `backend/app/services/oa_audit_access.py`；正式审计通过各业务服务读取权限和来源权限复核，未知引用拒绝。`oa_scope_service` 统一筛选；`audit_service` 保存线程 ID。
- 正式审计 API 按显式权限开放；导出创建/详情/下载复核当前身份、创建者/租户、审计范围、记录可见性、过期和文件哈希，内部元数据不进入公开 DTO 或导出正文。该实现仍待完整回归及实施者复核。
- `test_m3_p2_p3.py` fixture 补显式报表权限并移除不存在的虚构报表引用。它仍只是策略/审计证据，不能代表六场景通过。

## 实际验证和失败

改动前 `data/verification/m3/b5-resume-regression-2.log` 为 69 通过、4 警告。最新命令如下，已结束并收集退出状态 1：

```powershell
backend\.venv\Scripts\python.exe backend/scripts/m3_verify.py --log b5-audit-export-green-3.log tests/integration/test_m3_audit_authority.py tests/security/test_m3_scope.py tests/integration/test_m3_p2_p3.py tests/api/test_audit_export.py tests/integration/test_m3_faq_graph.py tests/integration/test_m3_document_sources.py
```

结果：45 通过、1 失败、4 警告。`backend/app/api/routers/audit.py:93` 将正式 UUID 字符串传给 `backend/app/schemas/audit.py:33` 的整数 `AuditEventOut.id`，引发 Pydantic ValidationError。失败用例为 `test_formal_audit_http_uses_permissions_and_honors_filters`，其后续 HTTP 断言尚未全部执行。此问题未修复。

早期 RED 的 12 个失败中 9 个为 helper 设置错误，仅三个是业务行为失败；不能声称复现了 12 个业务缺陷。早期 green/green-2 日志有 helper/fixture 错误，保留为失败记录。运行会话 47935、65752、60491 均已收集结束。本轮没有启动新运行会话。

## 恢复顺序

1. 先调查 ID 响应契约，兼顾旧审计整数 ID 和正式 UUID、前端消费；修复后串行重跑上述命令。已存在失败用例，不补造修复前 RED。
2. 复核新审计引用及导出来源范围，酌情补导出后绑定撤销、文件篡改、线程筛选、调岗测试；随后串行扩大回归。历史 69 项通过不验证当前新改动。
3. 补真实 HTTP/JWT FAQ 和 PostgreSQL checkpoint 关闭后新运行时恢复测试；现有缓存快照 mock 不代表持久恢复。可复用 FAQ 测试 fixture 和 HTTP helper；关闭后必须新建 GraphRuntime，不能复用残留图对象。
4. 继续补正式请假/工单图、可信确认/工具/领域对账，完成 13 核心和 2 辅助矩阵。当前 actor_for_thread 仅接 FAQ；旧审批/工单等 builtin 路由的 503 不能作为交付。
5. 补齐六场景来源、导出、缓存、后台和调岗、报销派生任务/报表；复核 FAQ 缓存面对策略/阈值变化的校验，并核对内桥清单中的 for_context 归属。最后更新 B5/B7 和联合报告。

## 环境约束

仅使用 `oa_business_m3_test`、`oa_business_m3_preview_test`，数据库套件串行。模型/嵌入 Mock；SMTP 关闭或仅经批准的本机捕获服务。不得修改真实 `.env`、原/M1/M2 数据库、生产数据或真实外发。旧预览 5182/8012、5193/8013、5194/8014 保留，M3 使用 5195/8015；本轮未操作预览进程。

仓库无 HEAD，分支 `codex/m1-identity-foundation`，文件尚未跟踪；保留用户现有文件，不 reset/revert。不开子代理。实际日志和本机凭据在忽略的 `data/verification/m3/`，不得披露凭据。包装器接受完整测试 node ID，不接受 `-k`。手工编辑使用 apply_patch。
