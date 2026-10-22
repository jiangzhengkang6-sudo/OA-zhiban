# M2 状态与继续入口

更新：2026-10-19。状态：用户已批准的 B1–B6 本地工程实施、验证与实施者复核完成，见 [验收说明](../../docs/m2-manual-oa-acceptance.md)。

## 用户意图与授权边界

用户在 M1 完成后要求“继续吧”。据 [实施计划](../../docs/部门OA正式化实施计划-V1.1.md) 的下一阶段，继续推进 M2 人工请假与流程底座；该请求已用于调查和形成具体方案。M1 的“确认”仅批准 M1 B1–B5，不记作 M2 具体契约批准。

2026-10-18 用户在完整方案与执行方式的确认请求后回复“确认”，明确批准 M2 契约、B1–B6 串行实施及人工执行/逐批复核替代。批准适用同目录现有 proposal/specs/design/tasks/execution-contract/execution-plan；不扩大至生产部署、真实数据或外发。

## 已完成的规划

- [proposal.md](proposal.md)：问题、范围、明确排除和业务规则选择。
- [specs/manual-workflow.md](specs/manual-workflow.md)：13 项可测试规格，每项含 WHEN/THEN 场景。
- [design.md](design.md)：D1–D9，新业务表/接口、事务/授权/版本与 AI 开关。
- [tasks.md](tasks.md)：明确路径和接口、B1–B6、18 项任务及规格覆盖。
- [execution-contract.md](execution-contract.md)：已批准行为、测试义务和复核门槛。
- [execution-plan.md](execution-plan.md)：R1 人工串行，B1–B6 完成及实际验证结果。

## 决策与工具

工作流技能 contract-builder 的具体契约批准已由上述用户回复满足。ssf 及配套脚本/模板缺失、Git 无 HEAD，用户已批准人工计划/复核替代；不伪造 `.spec-superflow.yaml`、哈希、机器收据或独立审查。采用 build-executor 的逐场景 Red/Green、分批验证与复核纪律；按批准方式由当前实施者串行执行。

## 下一步

B1–B6 已完成。数据库恢复后最终后端联合回归 608 项通过（排除 1 项超出授权库范围的历史迁移测试）、前端 87 项、桌面/手机浏览器 6 项及构建通过。规格逐项对应见 tasks.md，失败修复与限制见 [联合验证](reviews/verification.md)。预览为 5194/8014，测试仅使用授权 M2 隔离库与 Mock 模型/嵌入，真实配置和旧预览保持。

下一阶段是 M3 本体 Provider、13 个内部桥接契约、通知投递与报销，应另行形成可审核的具体契约。M2 通知仍为 PENDING，不进行生产部署、真实组织/额度导入或正式归档；M2 完成不代表 PRD V1.5 全部完成。

2026-10-19 继续入口：M3 [独立方案和契约草案](../department-oa-business/planning-status.md) 已形成，等待本阶段批准；M2 原实现与验证证据保持，不借用 M2 确认代替 M3 授权。
