# M1 状态与交接

日期：2026-10-18。用户在执行契约呈现后回复“确认”，批准 M1 B1–B5 串行实施及人工记录替代。B1–B5 已完成并通过本地工程验证；未生产部署或正式归档。实际状态见 execution-plan.md 和 reviews/verification.md。

## 范围及结果

M1 已实现本地账号、可撤销会话、部门/岗位/成员/角色管理、业务资源权限、提交前动态授权、中文登录与组织界面。新增迁移 0023，保留 0022 及历史业务结构；未自动映射 Mock 历史人员。

工作目录为 E:/OA AGENT SYSTEM，分支 codex/m1-identity-foundation；仓库尚无 Git HEAD，本轮不暂存或提交。用户真实 .env、原业务数据库、豆包主用顺序及真实嵌入配置未修改。测试和独立预览均使用专用数据库、Mock 模型与嵌入。

## 工程证据

- B1–B4：reviews/B1.md 至 reviews/B4.md。
- 授权入口：authorization-inventory.md。
- 最终验证：reviews/verification.md。
- 操作与验收：../../docs/m1-identity-acceptance.md。
- 原始本地运行结果：../../data/verification/m1/，已忽略，不将凭证写入文档。

## 后续边界

本地预览为 builtin 身份 + Mock OA，仅用于 M1 验收。M2 流程、M3 正式业务 Provider/通知、业务待办转交、真实组织导入、生产部署均未实施。旧全局管理 API 在 builtin 模式明确 503，生命周期审计仍事务写入。合同/任务来源和参与人约束保留较窄范围。

## 人工流程说明

本机缺失 ssf 及技能配套脚本/模板。用户已批准由当前实施者人工执行和审查；未生成机器 guard、哈希收据、Git SHA、自动状态转换或归档确认。文档复选框记录实现与验证结果，不补造逐步骤 Red 顺序。评估规划时的“待批准”已由本轮明确批准替代。
