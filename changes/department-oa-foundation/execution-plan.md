# M1 人工执行计划 R1

2026-10-18，用户回复“确认”，批准 execution-contract.md 及本地人工记录替代工具。当前实施者串行执行；不派发开发 agent，不生成虚假的机器 guard 或 Git SHA。

分支：codex/m1-identity-foundation。仓库 HEAD 尚无提交，原文件均未跟踪；沿用工作目录，不自动提交或移动文件。测试目标 oa_identity_m1_test，与已有预览数据库隔离。

| 批次 | 依赖 | 状态 | 证据 |
| --- | --- | --- | --- |
| B1 | 契约批准 | 完成 | reviews/B1.md |
| B2 | B1 审查通过 | 完成 | reviews/B2.md |
| B3 | B2 审查通过 | 完成，B5 补兼容修正 | reviews/B3.md、authorization-inventory.md |
| B4 | B3 审查通过 | 完成 | reviews/B4.md |
| B5 | B4 审查通过 | 完成 | reviews/verification.md；后端 516、前端 74、浏览器 2 通过，构建成功 |

每批记录实际命令、结果和人工代码审查；失败先调查修正，依赖批次等待通过。此文件为用户批准的人工计划，不声称是 ssf 输出。
