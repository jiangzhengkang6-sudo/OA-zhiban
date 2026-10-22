# Document And Email Implementation Review

Reviewed: 2026-10-14. Scope: the uncommitted filesystem snapshot under `E:/OA AGENT SYSTEM`, including document/email services, schemas, generators, routers, migrations, task/thread/interrupt/audit integration, and the Vue workbenches/shared command handling.

There is no valid Git commit range in this repository. BASE/HEAD SHAs are unavailable and no SHA or ssf execution receipt is asserted. The user explicitly approved skipping the unavailable ssf gate and authorized finishing document and email modules together. This combined authorization is now recorded in both document and email scope contracts; no further start approval is required.

## Final Code Review Verdict: Pass

Re-reviewed the repaired uncommitted snapshot on 2026-10-14. The three Important findings below are resolved in the implementation. No unresolved Critical or Important finding remains in the reviewed document/email scope. This is a code-review verdict, not production/manual acceptance or an ssf receipt. The parent reports 284 backend tests and 45 frontend tests passing, with the frontend build successful. This reviewer independently read the browser result JSON: 12 ordinary browser tests and 6 isolated real-API browser tests passed, with zero errors, unexpected results, skips or flaky results.

## Initial Findings And Resolution

### Important: Refresh The Actor Used By Post-Generation Source Authorization

At `backend/app/services/document_service.py:228`, `_identity(actor)` discards the refreshed identity. The following `_source_access` call uses the old `actor.depts`. If the employee moves from an allowed department to a disallowed department during the awaited model call, current roles still pass but the old department authorizes the knowledge snapshot. The service then persists the draft and returns the now-restricted source text. This conflicts with D2/D6 current authority and revoked source access behavior. Use the refreshed actor for source checks and persistence; refresh after embedding retrieval as well. The parent has planned a focused repair and a midflight department-revocation regression test. At this report's initial writing, repair verification is pending.

Resolved on re-review: creation now refreshes identity and rechecks the retrieved snapshot before persisting/returning. Both successful generation and the PAUSED failure path assign the refreshed identity; document generation checks source access against that refreshed actor before saving any response. Focused test code covers department revocation during successful generation, during failing regeneration, and source permission revocation before detail/history/replay reads.

### Important: Invalid Model References Must Produce Durable PAUSED Recovery

At `backend/app/services/document_service.py:230` and `backend/app/services/email_service.py:186`, generation passes the model result to `_persist`. Invalid source references cause `_persist` to raise `AppException`, which each `_generate` immediately rethrows. A structurally valid model result with an invented reference therefore returns 422 and rolls back instead of saving the required redacted PAUSED state and exposing explicit retry. D5 requires dependency-output failures to be recoverable and replayable. Validate model DTOs and references within the model error boundary, independently of HTTP validation for user edits. The parent has planned this repair and focused invalid-reference tests; verification is pending.

Resolved on re-review: `_validated_draft` validates DTOs and all references inside the generation recovery boundary. Invalid model evidence now saves redacted PAUSED with no revision. User edit validation remains a rejected 422 command. Parameterized focused tests cover both document and mail invented model references, recovery/replay, and immutable prior versions.

### Important: Persistence Exceptions Are Misclassified As Model Failure

The same `_generate` try blocks encompass `_persist`, while broad `except Exception` saves PAUSED. This absorbs persistence bugs and failures into a model retry result. A SQLAlchemy flush error leaves the transaction unusable, so the attempted PAUSED audit cannot be committed; a non-database exception after modifying a record can leave partially modified state under PAUSED. This violates D5's atomic business/audit/idempotency transaction requirement. Keep persistence outside the model/dependency recovery try block so business persistence failures roll back, and reuse the same command key only after rollback. The parent reports reproducing this with focused persistence-failure tests and is moving persistence outside the recovery block. Review has not independently run those tests.

Resolved on re-review: `_persist` now runs outside the model error boundary in both services. Persistence exceptions propagate to request transaction teardown and cannot be converted into a successful PAUSED result. Focused tests inject persistence failure, verify the record remains CREATED after rollback, then reuse the same command key successfully for exactly one revision.

## Minor Observations

Resolved: admin scene selectors in `frontend/src/views/ConfigView.vue` and `frontend/src/views/DegradationView.vue` now include document/email. No remaining minor finding is required for this delivery.

## Additional Re-Review Checks

- Task listing now excludes document/email when the refreshed actor lacks any applicable role; focused tests check an empty scene task list after role revocation.
- Both generation failure paths refresh identity before returning a PAUSED result. Focused tests revoke roles during a failing model call and verify a denied response with the original CREATED state restored after permission restoration.
- Error reload buttons use the same dirty-edit confirmation guard as navigation. A failed save preserves draft text and the stable command key; cancelling reload preserves both.
- The reviewed frontend tests cover creation and subsequent navigation, stale route replies, editing/confirmation gates, terminal history, dirty navigation/reload cancellation and mail second confirmation. The parent reports the full frontend test suite at 45 passing tests and the full backend suite at 284 passing tests. Those results are attributed to the parent, not independently rerun by this reviewer.
- Final frontend re-review confirmed that email history comparisons render Chinese business fields rather than raw JSON. The real-API integration tests cover create, generate, edit, history, confirmation, refresh and task-center return navigation; cancelling the mail second confirmation asserts that no decision write occurs. Desktop/mobile overflow checks and screenshots are included. The serial drafting configuration isolates the real-API suites from ordinary browser tests. No new Critical or Important finding was identified.

## Checked Boundaries

- Owner and tenant restrictions cover document/mail detail, history, commands and idempotent replay. Administrators receive task summaries without other owners' body content or action permissions.
- Generation/editing append distinct revision rows; commands lock the business row, enforce the expected version, and complete business/audit/result together in the API transaction.
- Confirmation recomputes server checks and requires metadata/warning acknowledgment. External-contact/sensitive-attachment mail confirmation additionally requires the second confirmation flag. Terminal records reject fresh edit/regeneration commands.
- Workbenches disable confirmation for unsaved changes, reset acknowledgments after saved responses, guard dirty navigation, reject obsolete route responses, preserve attempt keys for transport retries, and avoid adding the mail-only decision flag to document commands.
- Generic thread messages, interrupt resume, task handoff and task retry cannot advance document/email workflows.
- Dedicated workbenches clear generic waiting timestamps; no mail send, forward, attachment processing, task/calendar write or OA publication path is present in these services.
- Audits contain hashes/status/version rather than raw bodies; query filtering correlates document/email business records to the requested tenant.
- Migrations are additive; nonempty business-table downgrades are refused.

## Verification Limits

This review was read-only except for this report. No database tests were run concurrently with the parent's database-reset tests. Real Ark model behavior, production authentication, external mail systems and manual acceptance are not asserted. The findings above are concrete code paths; database corruption, hypothetical production mail integration, or automatic recognition of external email domains are not additional findings or required scope.

The authorized mail addition is recorded in both local scope contracts. Full regression/build details belong in the parent's verification record; this report distinguishes parent-reported results from independently inspected browser evidence. An unavailable ssf receipt remains waived; it must not be represented as an actual workflow receipt.
