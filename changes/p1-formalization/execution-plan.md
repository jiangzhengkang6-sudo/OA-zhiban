# 执行计划 revision 1

模式：inline，用户要求自主推进、完成后汇报。范围：P1，当前工作波 B4。

隔离：当前项目目录原地实施，不修改用户目录 Git master 分支；无 spec-superflow CLI，以本文件和独立审查报告持久化进度。

| 波 | 任务 | 依赖 | 状态 |
| --- | --- | --- | --- |
| B1-safety | 1.2 测试隔离 | 无 | 通过：11 安全闸门测试 |
| B1-migrations | 1.1 迁移 | B1-safety 通过 | 通过：4 迁移测试、dev 备份与无损升级 |
| B1-commands | 1.3 幂等 | B1-migrations 通过 | 通过：幂等单元和真实数据库测试 |
| B1-access | 1.4 Provider/授权 | B1-commands 通过 | 通过：权限即时撤销和能力探测测试 |
| B1-review | 综合验证与复核 | B1 全部任务 | 自评通过，局限见 reviews/b1-review.md |
| B2 | 请假纠正 | B1 通过 | 通过：完整 migrations/api/graph 集成 55 passed；通知与编辑对账回归已修复 |
| B3 | FAQ/工单纠正 | B2 通过 | 通过：与 B2 合并验证 55 passed；草稿/交接/确认门禁已验证 |
| B4 | 会话中心与内置请假 | B3 通过；用户于 2026-10-12 明确“继续下一步”授权开工 | 完成待归档：Task 4.1、Task 4.2、Task 4.3 已实现；150 后端测试、16 前端组件测试、Edge 12 场景浏览器验收通过；ClamAV 未配置时 PENDING 限制已验证 |
| B5 | 客服运营闭环 | B4 已完成待归档；用户于 2026-10-13 明确“继续开发” | 完成：Task 5.1～5.4；后端 161 passed，前端 19 passed，构建与运行冒烟通过 |
| B6 | 文件型知识与版本治理 | B5 已完成；用户继续开发授权 | Task 6.1、Task 6.2 后端、Task 6.3、Task 6.4 基础页面完成；待最终 Batch 6 E2E 和策略运行时全面接入 |
| B7 | 审计、观测与降级 | B6 基础能力已完成；用户继续开发授权 | 已实现并完成自动化/服务冒烟；待管理员浏览器验收 |
| B8 | 真实 OA 与上线验证 | B7 通过且提供真实 OA 沙箱参数 | 进行中：B8.1、B8.2 自动化与 B8.3 角色入口 E2E 已通过；B8.4 部署演练/真实 OA 沙箱待补 |

实施补充文件（计划未列出但为职责隔离所需）：backend/app/db/safety.py、backend/app/db/migrations.py、backend/tests/unit/test_test_database_safety.py、backend/tests/unit/test_startup_safety.py、backend/tests/unit/test_api_envelope.py、backend/tests/conftest.py、backend/tests/api/test_foundation.py、backend/app/providers/__init__.py、backend/.env.example、docs/manual-verification.md、README.md、.gitignore。工具、会话资源授权及 Provider 兼容必须接入 backend/app/tools/base.py、backend/app/api/deps.py、backend/app/api/routers/threads.py、backend/app/api/routers/tickets.py、backend/app/schemas/common.py、backend/app/services/thread_service.py、backend/app/adapters/mock_data.py；只修复当前路径，不增加新业务场景。旧 B1 文件清单里的 backend/tests/migrations/__init__.py 并非 pytest 所必需，不创建空文件。

基线证据：19 个单元测试通过；前端 npm run build 成功（存在打包体积告警）。开发库和 Mock 状态文件不得被测试修改。

本轮增量（2026-10-12）：内置请假预检通过后创建稳定 `AgentThread`，关联正式 `ApprovalInstance` 与有序 `ApprovalNode`；新增 `POST /api/leaves/{id}/decision` 供当前审批人提交内置审批决定；员工/当前审批人任务投影与两级审批幂等回归已覆盖。新增迁移 `0006_builtin_leave_thread`，全量验证 `117 passed`。

本轮增量（2026-10-13）：B6 Task 6.1 完成。新增 `DocumentParseError` 稳定错误码、10 MiB 文件大小边界、UTF-8 编码校验、PDF 解析错误收敛和 `knowledge_version` 上传/预览 DTO；验证 `backend/tests/unit` 为 63 passed。未修改现有知识表，版本生命周期留待 Task 6.2。

本轮增量（2026-10-13）：B6 Task 6.2 开始。新增 `knowledge_source`、`knowledge_version`、`knowledge_file` 四层模型中的前三层及 `0010_knowledge_source_versions` 非破坏迁移；开发库已从 `0009` 升级至 `0010`，迁移模型一致性和后端全量回归通过。尚未切换旧知识检索路径。

本轮增量（2026-10-13）：B6 Task 6.2 后端核心完成。新增迁移 `0011_knowledge_chunk_version`，版本创建/上传、解析就绪、显式发布、同源旧版本下线、历史版本递增和有效期/权限过滤检索均已接通；开发库已升级至 `0011`，后端全量 `182 passed`，前端 `19 passed`，构建成功。Task 6.2 尚未整体完成，待补版本治理页面和策略版本发布/回滚。

本轮增量（2026-10-13）：B6 Task 6.3/6.4 基础完成。新增不可变策略版本迁移 `0012`、阈值校验、作用域解析、发布/回滚/历史列表 API；新增来源治理与策略版本页面及管理员菜单入口。开发库已升级至 `0012`，后端全量 `186 passed`，前端全量 `19 passed`，构建成功。策略版本尚未替换全部旧运行时读取路径，需在 Batch 6 最终 E2E 中验证后再宣称退出。

本轮增量（2026-10-13）：策略版本已接入场景开关、运行时阈值、工具授权和调度器读取路径，并保留无版本时的旧 `agent_policy` 回退。修复测试隔离遗漏：新增 `policy_version` 后，各 HTTP/任务 fixture 均同步清理该表，避免策略版本测试残留导致后续工单被错误降级。策略作用域优先级与工单中断动作回归通过；后端全量 `187 passed`，前端 `19 passed`，构建成功。B6 仍待最终手工 E2E 验收，B7～B8 尚未开始。

本轮增量（2026-10-13）：B7.1～B7.4 已实现。新增审计受控导出、运行指标/trace 下钻、模型用量缺失标记、场景降级与在途任务策略，以及管理员运维观测/降级控制页面。修正 `audit_export.expires_at` 模型与 `0013` 迁移的时区类型不一致问题；后端全量 `194 passed`，前端 `19 passed`，构建成功。开发库已保持在 `0015 (head)`，后端 `8001/healthz` 和前端 `5173` 冒烟通过，管理员降级列表和运行指标接口可读。B7 尚待使用管理员账号完成真实浏览器页面验收，B8 未开始。

本轮增量（2026-10-13）：B7 剩余页面入口已打开，运维观测和降级控制 API 已完成管理员冒烟验证。B8.1 开始：新增可配置真实 OA HTTP Adapter、认证头、只读有限重试、写入幂等键、能力探测和 `/api/readiness`；契约/启动安全定向测试 `14 passed`。尚未配置真实 OA 沙箱地址，因此真实 Provider 仍报告 `ready: false`，不会进入生产路径。
本轮增量（2026-10-13）：B8.2 安全、恢复、性能门槛定向套件通过 `13 passed`；后端全量在显式测试库清理闸门下通过 `209 passed`（仅有既存 `datetime.utcnow()` 弃用警告）。B8.3 新增 Edge Playwright 五类演示角色菜单 E2E，连续两次运行均为 `5 passed`；前端组件测试 `19 passed`，生产构建成功。E2E 当前验证角色入口和菜单授权，不宣称已覆盖每类角色的完整业务闭环。
本轮增量（2026-10-13）：B8.4 已检查 `docker compose config --quiet`，现有 `oa-agent-db` healthy；未执行会清理卷或覆盖开发数据的部署操作。当前运行中的后端进程尚未加载 `/api/readiness`（访问返回 `404`），源码路由已挂载，需在可控窗口重启后端后复验。Docker 镜像构建仍受基础镜像 registry 异常影响，真实 OA 沙箱地址/凭据尚未提供，因此 B8 尚不能结项或宣称上线。
本轮增量（2026-10-13，本地验证）：在不接入真实 OA 的前提下，Mock Provider readiness 通过（`/api/readiness` HTTP 200，`ready: true`，identity/leave_read/approval_write/ticket_write/notification 全部可用）；后端全量 `209 passed`，前端 `19 passed`、构建成功，Edge E2E `5 passed`，Compose 配置校验通过且数据库容器 healthy。B8 仍保留“真实 OA 沙箱、运行中后端重启、完整部署/回滚演练”未完成状态。
