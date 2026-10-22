# B4 Task 4.3 frontend/workbench review — 2026-10-13

## Scope

任务中心、请假列表/表单、审批待办与详情页；真实附件上传、扫描状态、受控下载和审批材料展示。

## Evidence

- Frontend component suite: `16 passed`.
- Production build: `npm run build` passed; Vite only emitted an existing large-chunk warning.
- Backend regression: `150 passed` against isolated `oa_agent_test`.
- Edge + Playwright browser acceptance: `12 scenarios passed`, `page_errors: []`; screenshots and JSON result are under ignored `data/verification/b4-browser/`.

## Verified behavior

- Employee drafts survive refresh and resubmission creates immutable versions.
- Only the active approval node can decide; first-level approval activates the second level and final approval completes the application.
- Balance shortage, overlap, missing sick-leave proof and dependency pauses remain actionable without creating an invalid approval.
- Attachment metadata is visible to approvers; `PENDING`/failed scans disable download. With ClamAV unconfigured, real uploaded PNGs remain `PENDING` after rescan and refresh.
- Rejected applications and approver edits preserve prior versions and rerun precheck.

## Assessment

Task 4.3 passes review. B4 is ready for release-archivist verification; B5 remains out of scope.
