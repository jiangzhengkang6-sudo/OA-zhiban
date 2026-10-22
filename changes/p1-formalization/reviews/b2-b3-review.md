# B2/B3 review — 2026-10-12

## Scope

- B2: current-node approval authorization, ordered transitions, decision idempotency, lost external-write/notification recovery, and node-level scheduler behavior.
- B3: durable human handoff queue and redacted snapshot, editable ticket draft persistence, and FAQ/ticket graph integration.

## Evidence

- `backend/tests/api/test_approval_permissions.py`: 5/5 passed in the isolated test run before the local Docker database became unavailable.
- `backend/tests/unit/test_b3_services.py`: 3/3 passed.
- `python -m compileall -q app migrations`: passed.
- `frontend`: `npx vue-tsc -b` passed.
- Existing lost-outcome tests cover notification and ticket-edit response loss without duplicate delivery/write.

## Docker integration verification

Docker Desktop was restarted and the isolated PostgreSQL test database became available (`oa_agent_test`, host port `5433`). No development database was cleared or used as a substitute. With `ALLOW_TEST_DATABASE_RESET=true`, the complete targeted suite passed:

```text
python -m pytest tests/migrations tests/api tests/graph -q
55 passed in 18.86s
```

The five previously failing cases were reproduced first, then repaired and re-run as a focused regression set (`10 passed`).

## Findings

### Critical

None found in the reviewed scope.

### Important

None found in the reviewed scope. B3 integration evidence remains pending the isolated PostgreSQL test service.

### Minor

- The repository's Git root is above the project directory, so standard diff/receipt tooling cannot provide a project-local commit range. File-level review and persisted evidence are used instead.

### Repairs verified

- Notification failure now persists `UNKNOWN` using the bounded shared dependency error code, so the transaction cannot roll back the idempotency record.
- Approval reconciliation now distinguishes final approval, outcome notification, and leave-form edit writes. Edit reconciliation validates the original payload and authoritative OA result, resolves the original idempotency record, and resumes the checkpoint without reapplying the edit. Unauthorized or unconfirmed results remain `403`/`502` and paused.
- Ticket extraction stores `missing_fields` in `extracted_fields` metadata while keeping only editable fields in the draft `fields` map.

## Assessment

**Ready for the next existing-feature batch:** Yes, with the Docker integration verification explicitly outstanding.

**B4+ status:** Not started and not authorized by this report; those batches still require separate user approval.
