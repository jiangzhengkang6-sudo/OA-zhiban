# Document Agent Tasks

## Delivery Status (2026-10-14)

All four implementation batches are complete under the user's combined document/email authorization. Final local checks: backend 284, frontend 45, ordinary browser 12 and real API desktop/mobile 6 passing tests; production build and code re-review pass. Evidence: reviews/verification.md and docs/p2-document-acceptance.md. Human business and production acceptance remain outstanding; no ssf receipt or workflow archive is asserted.

## File Structure

- Create backend/app/models/document_record.py: owned input, template snapshot, evidence and terminal confirmation.
- Create backend/app/models/document_draft_version.py: immutable document revisions.
- Create backend/migrations/versions/0017_document_agent.py: additive two-table migration with guarded downgrade.
- Create backend/app/schemas/document.py: validated input, draft, command and response contracts.
- Create backend/app/services/document_templates.py: versioned template catalog and server checks.
- Create backend/app/services/document_generator.py: pure mock/Ark drafting using LLMFactory.
- Create backend/app/services/document_service.py: ACL, retrieval, replay and state transitions.
- Create backend/app/api/routers/documents.py: document command/read routes.
- Modify backend/app/models/__init__.py and backend/app/main.py: register models and API.
- Modify backend/app/services/task_service.py: safe document task projection and retry routing.
- Modify backend/app/services/thread_service.py and backend/app/services/interrupt_service.py: prevent generic graph bypasses.
- Modify backend/app/repositories/audit_repo.py: filter document audit by tenant.
- Create backend/tests/unit/test_document_templates.py and backend/tests/api/test_document_http.py: behavioral/security tests.
- Create frontend/src/api/document.ts and frontend/src/views/DocumentView.vue: document transport and workbench.
- Modify frontend/src/types/index.ts, frontend/src/router/index.ts, frontend/src/App.vue, frontend/src/views/TaskCenterView.vue and frontend/src/utils/status.ts: typed navigation and task integration.
- Create frontend/src/tests/drafting-workbenches.test.ts, frontend/src/tests/draft-command-keys.test.ts and frontend/e2e/p2-drafting-integration.spec.ts: combined document/email browser/component regression tests.
- Create docs/p2-document-acceptance.md and changes/p2-document-agent/reviews/verification.md: actual evidence and manual acceptance checklist.

## Interfaces

Batch 1 produces DocumentInput, DocumentDraftDTO, DocumentResponse, DocumentCommand, DocumentDecision, DocumentRecord, DocumentDraftVersion and template/check functions. Batch 2 consumes these and produces the /api/documents endpoints plus document task projections. Batch 3 consumes JSON DocumentResponse and template/version arrays via documentApi. Batch 4 consumes all preceding behavior and records actual verification.

## Execution Batches

### Batch 1: Domain Contracts (D1/D3/D4)

1. Write schema/template tests in backend/tests/unit/test_document_templates.py (RED, 2-5 min).
2. Run the focused tests and inspect the missing-module failure (2 min).
3. Implement backend/app/schemas/document.py and backend/app/services/document_templates.py (GREEN, 5 min per atomic type/function).
4. Run focused tests and verify real invalid/valid cases (2 min).
5. Review validation bounds and sensitive messages, refactor only affected helpers (2-5 min).

Interfaces: produces validated document types and deterministic checks. Depends on: none.

### Batch 2: Persisted Commands And API (D1-D6)

1. Write lifecycle, replay, stale-version, tenant/source ACL, failure recovery, audit and zero-external-write HTTP tests in backend/tests/api/test_document_http.py (RED, 5 min per case).
2. Run focused tests against oa_agent_test and inspect missing-route failures (2 min).
3. Implement the models, migration, document_service/document_generator/documents router, registrations and task/audit/generic-endpoint guards listed above (GREEN, 5 min per atomic method).
4. Run focused HTTP tests and prior meeting/task regression tests (5 min).
5. Review transaction/ACL boundaries and reconcile contract coverage before UI work (5 min).

Interfaces: consumes Batch 1 types; produces persisted DocumentResponse, document version arrays and task projection. Depends on: Batch 1.

### Batch 3: Document Workbench (D1/D3/D4/D6)

1. Write frontend/src/tests/drafting-workbenches.test.ts and draft-command-keys.test.ts for creation, stale route responses, unsaved edit confirmation guard, immutable comparison and command replay keys (RED, 5 min per case).
2. Run the focused frontend test and inspect missing-view/behavior failures (2 min).
3. Implement the listed frontend API/types/view/navigation files with loading/error/empty/terminal states (GREEN, 5 min per component action).
4. Run frontend tests and production build, then browser lifecycle checks at desktop/mobile viewports (5 min per check).
5. Review action availability, source visibility, text overflow and version reset on navigation (5 min).

Interfaces: consumes Batch 2 JSON contracts; produces /documents/:id? and task navigation. Depends on: Batch 2.

### Batch 4: Verification (D1-D6)

1. Add frontend/e2e/p2-drafting-integration.spec.ts for the combined visible document/email creation/edit/review lifecycle (RED, 5 min).
2. Run it and inspect any real failure before changing affected code (2 min).
3. Repair only the failed behavior and document the investigation (GREEN, 5 min per defect).
4. Run the full backend/frontend suites, build and selected browser regressions against isolated services/databases (5 min per check).
5. Record tests, review findings, residual manual checks in docs/p2-document-acceptance.md and reviews/verification.md (5 min).

Interfaces: consumes all batches; produces test evidence and a reviewable acceptance record. Depends on: Batch 3.
