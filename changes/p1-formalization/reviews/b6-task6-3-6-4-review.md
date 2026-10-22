# B6 Task 6.3/6.4 review — 2026-10-13

## Scope

覆盖不可变策略版本、阈值校验、作用域优先级、发布/回滚/历史列表 API，以及知识来源和策略治理前端页面。

## Verification

- `pytest -q backend/tests/api/test_policy_versions.py backend/tests/unit/test_policy_version_service.py`：4 passed。
- `pytest -q backend/tests --disable-warnings --maxfail=1`：187 passed。
- `npm test -- --run`：19 passed。
- `npm run build`：成功。
- 开发库迁移头：`0012`。

## Findings

- 策略发布后不可覆盖；回滚创建新版本并保留旧版本。
- 版本列表可按场景加载，页面提供发布和回滚操作。
- 场景开关、运行时阈值、工具授权和调度器已优先读取已发布策略版本；无版本时仍回退旧 `agent_policy`。
- 修复测试 fixture 未清理 `policy_version` 的隔离缺口，避免策略版本测试残留改变后续 HTTP 流程。
- 前端测试仍有 Element Plus 图标解析 warning，但不影响测试结果和构建。

## Verdict

Task 6.3：基础能力及运行时接入 PASS；Task 6.4：基础页面 PASS；Batch 6：仍进行中，未宣称最终完成。
