# B6 Task 6.2 backend review — 2026-10-13

## Scope

覆盖来源/版本/文件模型、非破坏迁移、文件上传、草稿/发布生命周期、历史版本保留和版本化检索。

## Verification

- `pytest -q backend/tests/api/test_knowledge_versions.py`：4 passed。
- `pytest -q backend/tests/migrations/test_mvp_upgrade.py`：4 passed。
- `pytest -q backend/tests --disable-warnings --maxfail=1`：182 passed。
- `npm test -- --run`：19 passed。
- `npm run build`：成功。
- 开发库迁移头：`0011`。

## Findings

- 迁移 `0011` 对无版本 MVP 表兼容：若 ORM 预创建 `version_id`，迁移会检查后复用，不重复添加。
- 旧 `knowledge_document` 导入/检索保持兼容；版本化检索有发布版本时优先，否则回退旧路径。
- 当前未完成知识治理前端、策略版本发布/回滚、四层模型的关系加载优化及旧数据回填；这些不应被误报为 Batch 6 完成。

## Verdict

Task 6.2 后端核心：PASS。Batch 6：进行中。
