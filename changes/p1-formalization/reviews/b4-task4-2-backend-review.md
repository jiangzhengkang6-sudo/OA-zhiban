# B4 Task 4.2 backend application slice review — 2026-10-12

## Scope

内置请假申请后端子阶段：草稿创建/修改、不可覆盖版本、确定性预检、病假附件规则、所有权隔离、附件元数据模型和 Alembic 0005 迁移。审批接入、任务关联、附件上传存储和前端页面不在本次完成范围。

## Evidence

- RED: built-in leave API tests initially failed because the models/API did not exist.
- GREEN: focused tests passed: 3 passed.
- Regression: migrations/api/graph/unit suite passed: 115 passed in 18.65s.
- Static check: compileall passed.

## Verified behavior

- Drafts are tenant/user scoped and editable only in DRAFT/NEEDS_FIX.
- Submit creates an immutable application version and structured precheck items.
- Missing sick-leave attachments produce NEEDS_FIX and do not create an approval instance.
- Fixing the failed item and resubmitting creates the next immutable version.
- Async ORM server-default timestamps are explicitly refreshed.

## Deferred

- Formal approval graph/workbench connection.
- Real attachment upload/scan/storage integration.
- Frontend leave list/form/approval inbox.

## Assessment

This backend application slice passes review. B4 remains in progress.
