# M3 状态与继续入口

更新：2026-10-20。状态：用户已批准 M3 契约。B1-B4 历史复核保留；B5、B6、B7 的批准本地范围已完成实施者串行验证，M3 进入验收材料和交付准备。生产上线、M4 和 V2 仍未完成。

## 用户意图

用户在 M2 完成后要求“继续推进吧”，据既有 [实施计划](../../docs/部门OA正式化实施计划-V1.1.md) 推进下一阶段 M3。现有意图与约束足以起草具体方案，不重新询问阶段名称或泛化需求；M1/M2 历史确认不被改写为 M3 的具体批准。

## 可审核文档

- [proposal.md](proposal.md)：范围、13 项计数差异与明确排除。
- [specs/formal-business.md](specs/formal-business.md)：M3-01 至 M3-14、C01-C13 及两个辅助读能力，每项含验收场景。
- [design.md](design.md)：D1-D8、0025-0028、共用引擎和独立正式权威、通知未知结果与来源权限。
- [tasks.md](tasks.md)：精确路径、跨批接口、五阶段验证步骤和需求覆盖。
- [execution-contract.md](execution-contract.md)：拟批准行为、范围、测试、复核和退回条件。
- [execution-plan.md](execution-plan.md)：R1，B1-B7 人工串行计划及实际批次状态。

## 工具与确认边界

本轮使用 workflow-start、spec-writer、contract-builder 的状态识别、规格和契约纪律。ssf 及技能配套脚本/模板缺失，Git 尚无 HEAD；没有运行成功的 machine guard，也没有伪造 yaml、SHA 或审查收据。按照用户继续推进的意图及开发者要求，先完成可审核的一整组草案再一次请求具体批准，不将起草文档写作实施完成。

contract-builder 的规则为 “DP-3 is a hard gate — no implementation without this record.” 2026-10-19 用户已针对新 M3 契约、专用两个库及人工串行/实施者复核替代明确回复“确认”；本记录保存实际批准，进入 B1，不借用 M2 批准。

## 本轮核验结论

1. OAAdapter 实际 11 个方法，外桥文档 12 条含 capabilities；工单写入对账缺失。本方案补 C11 后为 13 核心项；代码已调用的工单状态/字段字典另列辅助读。
2. M2 流程实例绑定 leave_version_id，审批/转交/调度需一同适配有类型主体，不能仅添加报销 scene。
3. 工单旧创建依赖适配器、合并 hash 排除目标；正式独立表和命令解决权威及幂等边界。
4. 原 outbox 无渠道尝试/租约/UNKNOWN，原用户无邮箱；新正式通知与收件配置不能假设已具备。
5. 旧策略/审计缺可靠租户归属，知识/报表存在旧数据回退风险；正式绑定/策略/审计及逐入口权限完成后才放开。

## 下一步

本轮规划验证：7 份非空文档、24 个本地链接有效，14 个需求各含 SHALL/MUST 与 WHEN/THEN 场景并全部映射到批次；13 个核心、2 个辅助契约；任务表现有 Modify 路径均存在、Create 路径未占用，无空占位。此为文档检查，不是业务测试、迁移通过或功能验收。

恢复入口见 [checkpoint-2026-10-20.md](checkpoint-2026-10-20.md)。最新联合结果见 [reviews/B7.md](reviews/B7.md) 和 [reviews/verification.md](reviews/verification.md)。报销浏览器夹具问题已修复并复验；当前日志不含测试失败。

本地 M3 范围按 [执行契约](execution-contract.md) 完成；来源/网关、合同权限/回归、前端、迁移、后台和浏览器证据均保留在 `data/verification/m3/`。真实模型、原数据库、旧预览和历史验收报告保持；不实际外发或生产部署。
