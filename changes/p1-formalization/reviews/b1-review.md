# B1 review — 2026-10-12

Review mode: self-review fallback. No `spec-superflow` script or independently configured reviewer profile exists on this host; this is **not** a machine review receipt or independent reviewer approval.

## Coverage

- P1-PLAT-003: baseline 0001 can adopt old `create_all` tables; 0002 adds command/span tables without editing MVP rows. Tested empty, legacy and mixed schema failure paths on isolated test DB; dev migration preserves `agent_thread=2`, `audit_event=18`, `knowledge_document=0`.
- P1-PLAT-004: destructive fixtures require environment=test, explicit allow flag, database suffix and three matching target identities; test Mock file moved to temporary path.
- P1-PLAT-005/007: durable command scope, canonical payload hashes, collision detection, PENDING rejection and explicit authoritative reconciliation available. Existing MVP writes are **not yet fully converted**; follow-on B2/B3 work must use the service before claiming end-to-end idempotency.
- F-011/F-013 groundwork: endpoint role revocation checked per request, resource tenant isolation tightened, tool wrapper checks live role and scene/policy whitelist. Several legacy graph nodes bypass the wrapper; B2/B3 must wire their new domain writes into it.
- Provider capabilities reject unsupported builtin and 501 real when starting; no silent mock fallback. Real OA and builtin are future batches.

## Findings and risk

- No production Mock acceptance: production auth, unsupported auth provider and real stub all fail startup. Passed dedicated tests.
- Old backend process may continue using loaded MVP code until restarted. `alembic upgrade head` has completed successfully on development DB, so restart is safe; rollout must restart the backend before claiming new auth checks active.
- Old documentation sections still demonstrate MVP's one-step approval; they are labeled as MVP-only; B2 manual verification must replace these steps.
- Existing data backup is held at `data/backups/oa-agent-before-b1-20261012-114239.dump`, ignored by the project `.gitignore`. It may contain sensitive business data; do not publish.

## Verification

- Red tests observed for safety/imports, migration missing, ORM/schema drift, idempotency and auth before production edits.
- Green: `python -m pytest tests/unit -q` 47 passed; `ALLOW_TEST_DATABASE_RESET=true python -m pytest tests/migrations tests/api tests/graph -q` 22 passed; `python -m alembic current` 0002 head; `npm run build` passes (existing >500kB chunk warning).

Verdict: B1 foundational work ready to proceed to B2, with documented constraints above. This report does not claim that F-011/F-013 or every write API is formally complete.
