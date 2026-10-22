# Document And Email Verification

Verified: 2026-10-14. Snapshot: uncommitted files in `E:/OA AGENT SYSTEM`, branch `codex/p2-meeting-agent`. Scope: document D1-D6 and email E1-E5, under the user's explicit combined-development and unavailable-ssf-gate bypass authorization. No commit range or machine execution receipt exists.

## Final Results

| Check | Command | Result |
| --- | --- | --- |
| Backend full suite | `python -m pytest -q` with the test environment below | 284 passed, 0 failed, 4 warnings; 119.68 seconds |
| Frontend full suite | `npm test` | 45 passed, 0 failed, 10 files |
| Production build | `npm run build` | Exit 0; vue-tsc and Vite succeed |
| Existing browser regression | `npm run test:e2e` | 12 passed, 0 failed; 11.5 seconds |
| Real API desktop/mobile | `npx playwright test --config playwright.drafting.config.ts` | 6 passed, 0 failed; final 27.2 seconds |
| Code re-review | `document-email-review.md` | Pass, no unresolved Critical/Important findings |

These are locally executed results, not CI or production acceptance. Original backend terminal output was read but not separately saved. Browser JSON files are retained and overwritten by subsequent runs: `frontend/data/verification/p2-drafting/result.json` and `frontend/data/verification/b8-browser/result.json`. Four review screenshots are retained under `frontend/data/verification/p2-drafting/browser/`. Desktop 1440x960 and mobile 390x844 screenshots were visually inspected; browser assertions verify nonblank workbenches and no horizontal page overflow. Mail comparison displays readable business fields instead of raw JSON.

## Reproduce Backend Safely

Run from `backend/` with system Python. Stop any service using this test database before executing reset-enabled tests. All three database connections are explicitly restricted to the separately validated test database; `oa_agent` is never truncated.

```powershell
$env:ENVIRONMENT='test'
$env:ALLOW_TEST_DATABASE_RESET='true'
$env:DATABASE_URL='postgresql+asyncpg://oa:oa@localhost:5433/oa_agent_test'
$env:DATABASE_SYNC_URL='postgresql+psycopg://oa:oa@localhost:5433/oa_agent_test'
$env:CHECKPOINTER_URL='postgresql://oa:oa@localhost:5433/oa_agent_test'
python -m pytest -q
```

The final reset test run finished before browser backend startup. Migrations 0017 and 0018 add four tables. Migration tests use disposable schemas and check table fields/FKs/uniques, repeated head upgrade, empty downgrade/reupgrade, and refusal to downgrade either module with retained business data. The migration ledger reaches 0018 in the test database only. Existing meeting migration tests target their own 0016 revision instead of assuming it remains the repository head.

## Reproduce Real API Browser Checks

Run the backend in a separate terminal from `backend/`. `run.py` supplies the Windows-compatible SelectorEventLoop. Use reset-disabled test mode and Mock providers:

```powershell
$env:ENVIRONMENT='test'
$env:ALLOW_TEST_DATABASE_RESET='false'
$env:OA_BACKEND_PORT='8012'
$env:DATABASE_URL='postgresql+asyncpg://oa:oa@localhost:5433/oa_agent_test'
$env:DATABASE_SYNC_URL='postgresql+psycopg://oa:oa@localhost:5433/oa_agent_test'
$env:CHECKPOINTER_URL='postgresql://oa:oa@localhost:5433/oa_agent_test'
$env:LLM_PROVIDER='mock'
$env:OA_PROVIDER='mock'
$env:AUTH_PROVIDER='mock'
$env:MOCK_STATE_FILE='data/verification/p2-drafting/mock_state.json'
python run.py
```

Run the frontend in another terminal from `frontend/`:

```powershell
$env:OA_BACKEND_PORT='8012'
npm run dev -- --host 127.0.0.1 --port 5182 --strictPort
```

Then run from `frontend/`:

```powershell
npx playwright test --config playwright.drafting.config.ts
```

The real API config has no automatic webServer or database reset. Its six cases make actual FastAPI/database calls with no API interception. Default `playwright.config.ts` excludes both real integration specs; the ordinary 12-case suite retains its simulated API responses. The 5182/8012 preview services remain available for local review; original 5173/8001 services were not stopped or repurposed.

## Requirements And Evidence

| Requirement | Implementation | Verification |
| --- | --- | --- |
| D1 templates and input | document schema/templates; create snapshots | unit/test_document_templates.py; api/test_document_http.py; real UI creation |
| D2 authorized evidence | document_service filtered retrieval, snapshots and refreshed source checks; generator treats evidence as data | api/test_drafting_boundaries.py actual knowledge filters, success/failure midflight department revocation and replay denial |
| D3 revisions and checks | document_draft_version, locked expected-version save, server checks | document HTTP stale/concurrent edits; migration uniques; UI v1/v2 comparison |
| D4 human finalization | document decisions, saved-version metadata/risk acknowledgments and terminal guards | HTTP confirmation/zero writer calls; UI dirty/unchecked guards and terminal reload |
| D5 recovery and atomicity | scoped idempotency, PAUSED/retry, model-output validation separated from persistence | shared failure/replay/retry, invalid model references, persistence rollback and same-key recovery tests |
| D6 platform isolation | task/audit projection, generic graph guards, scene policy controls and Vue routes | role/tenant/policy/degradation tests; dirty-route/reload and stale-response component tests; real task-center reopen |
| E1 owned input/evidence | email schema/snapshots, owner/tenant authorization | email HTTP and shared revocation/tenant tests |
| E2 analysis/revisions | email generator/schema, email_draft_version, reference checks | email HTTP and shared invalid-evidence/stale-edit tests; UI revision comparison |
| E3 explicit confirmation | warning metadata guards, independent secondary flag/modal, terminal protection | email server secondary/terminal tests; real cancel yields zero decisions POST; final confirm/reload |
| E4 recovery/commands | locked atomic command/result/audit, refreshed identity after both success/failure | shared persistence/failure/retry/revocation tests for both scenes |
| E5 controls | task/thread/interrupt/audit integration, admin scene selectors and guarded workbench | shared generic bypass/policy/roles tests; component and real-browser task navigation |

## Repairs Verified

- Midflight actor/source authorization previously retained old departments; both generation success and failure now use refreshed identity. Retrieval also refreshes identity after embedding await. Denials roll back state and reveal no revoked source content.
- Invalid model references now produce durable redacted PAUSED; user-invalid edits remain validation errors with no revision.
- Persistence failures occur outside the model recovery boundary and roll back; same-key recovery produces one revision instead of misclassifying a storage failure as a model pause.
- Role-revoked document/email tasks disappear from task lists, and failed model calls cannot return stored content after role revocation.
- Failed client saves preserve edits and retry keys; dirty navigation and error reload share the leave guard. Creation clears busy before route navigation.
- The first full backend run found the prior meeting test's hardcoded 0016 head. A new empty-downgrade test initially used the inspector's implicit search_path and saw fallback public tables; it now explicitly inspects the temporary schema. Final full suite passes all 284 cases.
- Initial real-browser scripts targeted Element Plus internal select/switch/checkbox inputs obscured by placeholders or hidden by CSS. Tests now click the actual visible wrapper/label and assert selected state; no forced click or removed functional assertion was used. Final desktop/mobile run passes six cases.

## Completeness And Limits

| Dimension | Local engineering result | Notes |
| --- | --- | --- |
| Completeness | PASS | D1-D6/E1-E5 mapped above; domain/API/workbench/verification batches complete |
| Correctness | PASS | full backend/frontend suites, build and browser regressions pass; review fixes covered |
| Coherence | PASS | scope/docs record combined authorization, four additive tables and internal-only decisions |

The built frontend still has the existing approximately 1.268 MB main chunk warning; App unit tests emit icon-resolution warnings from their test stubs. Backend emits four existing datetime.utcnow deprecation warnings in audit export. These were not concealed or treated as new test failures.

Manual business tests T24-T29 are documented but not executed by a human. Real Ark semantics/quality, production authentication, real OA publication/mailbox integration and production deployment are unverified. Mock OA write-method spies plus service/traffic checks demonstrate the implemented local scope, not actual external integration. Attachment bytes and external task/calendar/mail/file writes are excluded. Confirmation is an internal saved result only.

Scope records and README/API/manual docs have been synchronized. No main spec base exists for automatic delta merge. Unavailable ssf scripts were explicitly waived; no synthetic DP records, base/head SHA, archive or approval receipt is created. The delivery is locally verified development, not full production P2 acceptance.
