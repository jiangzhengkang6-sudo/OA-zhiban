# P2 文档起草验收记录

日期：2026-10-14。范围：`changes/p2-document-agent/specs/document-agent.md` D1-D6。用户已明确批准跳过不可用的 ssf 门禁，并连续完成文档与邮件开发。本记录确认本地实现和自动化验证结果；人工业务验收、真实模型输出质量与正式上线验收仍待完成。

## 已实现

- 公文、通知、报告、总结四类版本化模板；标题、对象、期限、依据、要点、密级和分发范围录入。
- 可选知识引用：限定当前租户、部门权限、已发布、生效且 READY 的版本，保存来源位置、版本、哈希和材料快照。材料中的指令按数据处理。
- 生成、人工修订、不可变版本历史、正文比较、格式与基础敏感信息检查；未保存修改禁止确认并保护离页/重新加载。
- 按保存版本核对元数据与风险提示后确认内部记录；拒绝、重新生成、暂停与显式重试。
- 租户/本人权限、即时撤权、版本冲突、请求幂等、事务回滚、脱敏审计、任务中心进入及策略/降级开关。

## 验证结果

| 层级 | 命令 | 最终结果 |
| --- | --- | --- |
| 后端全量 | 测试环境变量见共享验证记录；`cd backend; python -m pytest -q` | 284 passed，0 failed；4 条既有审计时间弃用警告 |
| 前端 | `cd frontend; npm test` | 45 passed，10 个文件；既有 App 测试图标 stub 警告 |
| 构建 | `cd frontend; npm run build` | 退出码 0；既有大 chunk 提示 |
| 原有浏览器回归 | `cd frontend; npm run test:e2e` | 12 passed，0 failed，角色入口与会议流程 |
| 真实接口浏览器 | `cd frontend; npx playwright test --config playwright.drafting.config.ts` | 6 passed，0 failed；文档、邮件、会议各桌面/手机一例 |
| 代码复审 | `changes/p2-document-agent/reviews/document-email-review.md` | Pass；无未解决的 Critical/Important 问题 |

真实接口用例不拦截 API，使用 5182 前端、8012 后端与独立 `oa_agent_test`。文档用例覆盖创建、生成 v1、编辑保存 v2、历史正文比较、元数据确认、终态刷新和任务中心回跳；断言没有页面运行错误、工作台横向溢出或文档接口以外的写请求。后端对 Mock OA 的写方法进行零调用断言；浏览器流量本身不构成真实 OA 联调证明。

共享证据与复现环境：`changes/p2-document-agent/reviews/verification.md`。机器结果：`frontend/data/verification/p2-drafting/result.json`、`frontend/data/verification/b8-browser/result.json`。截图保存在 `frontend/data/verification/p2-drafting/browser/`；重新运行会覆盖这些文件。终端输出未另存为 CI 日志。

## 试用与待验收

本次保留的预览地址：`http://127.0.0.1:5182/documents`，选择“张三 · 员工”。此服务使用测试数据库和 Mock 身份/模型/OA。实际开发库 `oa_agent` 未运行本批清空测试；新增迁移 0017/0018 仅在测试库验证，不表示开发库或正式库已升级。

人工步骤见 `docs/functional-test-guide.md` T24-T26、T29，结果尚待填写。真实 Ark 的事实准确性、引用正确性和文种质量，以及正式身份系统、真实 OA 发文和生产部署未验收。基础敏感模式检查不提供完整 DLP 或法定公文格式认证。

确认只保存平台内记录；不发文、盖章、外部归档、导出附件，也不创建外部任务或日历。未生成 ssf 机器回执、Git SHA 或工作流归档状态。
