# P2 邮件模块验收记录

日期：2026-10-14。范围：`changes/p2-email-agent/specs/email-agent.md` E1-E5。用户已授权与文档模块一起完成开发，并批准跳过不可用的 ssf 门禁。本地开发和自动化验证完成；真实邮箱、实际模型质量、人工业务验收与上线验收尚未完成。

## 已实现

- 手动录入主题、发件人、收件人、正文、外部联系人标记和附件名称/敏感标记；保存本人所属租户的输入与逐行来源快照。
- 分类、优先级、摘要、待办候选、谨慎回复草稿；原文未明确的负责人和期限留作人工确认。
- 修改分析与回复、保存不可变新版本、以中文业务字段比较历史版本、来源核对。
- 保存前的未改动版本要求、元数据与风险确认；外部联系人或敏感附件额外要求独立二次确认，取消不会提交决定。
- 终态保护、暂停/重试、作用域幂等、行锁与版本冲突、原子审计、即时撤权、任务中心回跳及策略/降级控制。

“外部联系人”由用户明确标记，不自动推断邮箱域名。附件仅保存元数据，不接收或解析实际文件字节。待办只是候选，不自动生成任务。

## 验证结果

| 层级 | 命令 | 最终结果 |
| --- | --- | --- |
| 后端全量 | 测试环境变量见共享验证记录；`cd backend; python -m pytest -q` | 284 passed，0 failed |
| 前端 | `cd frontend; npm test` | 45 passed，0 failed |
| 构建 | `cd frontend; npm run build` | 退出码 0 |
| 原有浏览器回归 | `cd frontend; npm run test:e2e` | 12 passed，0 failed |
| 真实接口桌面/手机 | `cd frontend; npx playwright test --config playwright.drafting.config.ts` | 6 passed，0 failed；邮件两例，另含文档/会议回归 |
| 代码复审 | `changes/p2-document-agent/reviews/document-email-review.md` | Pass；无未解决的 Critical/Important 问题 |

真实邮件用例经 5182/8012 服务与 `oa_agent_test` 创建外部联系人/敏感附件记录，分析 v1，修订回复到 v2，核对历史与当前业务字段，取消一次二次确认且未发出 decisions 请求，再确认、刷新终态并从任务中心回到同一邮件。覆盖风险未勾选不能确认、无页面运行错误、无横向溢出及邮件接口以外的写请求。后端测试另外验证权限、并发/幂等、无外部 OA 写方法调用和事务失败回滚。

复现命令、迁移/安全边界和已修复问题见 `changes/p2-document-agent/reviews/verification.md`。机器结果见 `frontend/data/verification/p2-drafting/result.json`，截图位于其 `browser/` 子目录；重新运行会覆盖证据文件。后端原始终端输出未单独存档。既有时间弃用、测试图标 stub 和构建大 chunk 警告均记录在共享报告。

## 试用与待验收

预览地址：`http://127.0.0.1:5182/emails`，选择“张三 · 员工”。运行环境为测试数据库、Mock 身份/模型/OA。迁移 0018 仅在独立测试库验证；未声明开发库或生产库已升级。

人工步骤见 `docs/functional-test-guide.md` T27-T29，实际结果待填写。真实 Ark 的分类、摘要、待办与回复质量，生产认证、真实邮箱读取/发送及部署验收均未完成。

确认只形成平台内部记录；没有发送、转发、邮箱同步、附件内容处理、外部任务或日历写入。不能将 `CONFIRMED` 描述为“邮件已发出”。无 ssf 机器回执、Git SHA 或自动归档声明。
