# M4 Execution Contract (User Approved; Workflow State Unrecorded)

## Why

Establish repeatable security, deployment, backup, isolated recovery, degradation, and rollback verification using synthetic data in a local isolated environment. This closes the resilience evidence gap after M1-M3 feature validation; it is not production launch or server migration approval.

## Approved Behavior

The following behavior is derived from the confirmed `proposal.md`, `specs/resilience.md`, `design.md`, and `tasks.md`. It remains pending until explicit DP-3 approval:

- M4 drills use only a dedicated Compose project, database, volumes, and file directories with synthetic data. Validate target allowlists before writes. Never access, overwrite, or clean existing M1/M2/M3 preview data, volumes, attachments, or credentials.
- Backups cover PostgreSQL (including LangGraph checkpoints), attachments, knowledge source files, and a non-sensitive configuration manifest. Verify integrity with a manifest, path checks, and SHA-256. Keep secrets separate from data backups; never place them in the repository, ordinary manifests, or reports. Do not label same-host copies as offsite backups.
- Before restore, verify the backup and an explicitly selected, independent, empty destination. After restore, verify login, history, attachments, in-progress approvals, knowledge sources, checkpoint/business state, and idempotent replay of completed operations.
- Calculate RPO/RTO from recorded failure/recovery times and data verification evidence. Compare against PRD targets of RPO <= 24 hours and RTO <= 15 minutes at pilot data volume. Missing evidence or exceeded targets must be marked uncovered/failed; never claim success without evidence.
- Verify image build, configuration, migrations, readiness, and compatible application rollback. Production-like configuration rejects weak default credentials and unsafe Mock identity/OA Provider combinations. Prohibit destructive database downgrade; use forward repair or an independent recovery destination when incompatible.
- Using isolated data and mocked external dependencies, verify prompt injection, authorization boundaries, outbound controls, sensitive logs, and audit atomicity. No real outbound messages or paid model calls.
- Separately verify manual workflows with AI disabled, and fallback manual records, deduplicated replay, and reconciliation during/after system-of-record failure. Disabling AI is not system-of-record disaster recovery.
- Reports mark only evidenced items as passed and identify environment, dataset size, hardware, limits, and uncovered items. A single local drill does not prove offsite backups, recurring daily backups, weekly restores, or production availability.

## Scope Fence

**Included:** The six batches and 21 files listed in `tasks.md`: isolation baseline, production-like configuration checks, backup and verification, isolated restore and metrics, security/migration/degradation drills, deployment and rollback documentation, and acceptance evidence.

**Excluded:** Production/shared servers, DNS/HTTPS/firewall changes, real organization or pilot data, real `.env` files/secrets, M1/M2/M3 databases or volumes, real SMTP/OA/IM/scanning services, real model calls, server migration, and unrelated business or UI changes.

If a task requires touching an excluded resource, stop that batch. Do not probe, copy, clean, or migrate it; return to the user to reconfirm scope.

## Build Constraints

- Inspect the working tree and running services first. Do not clean/delete volumes, overwrite unknown directories, use real `.env` files, or publish a database port to an existing preview environment.
- Compose must use a unique M4 project, the M4-specific override, and temporary synthetic configuration; never rely on an implicit default target. Revalidate target identity before destructive actions; never run them against a source target.
- Use test-driven implementation and follow `tasks.md` dependencies serially. Do not pass failed security, migration, recovery, or review gates.
- Use synthetic test data and mocked external dependencies. Redact logs and evidence before recording; do not expose real credentials in output or archives.
- Never run database downgrade. Application rollback is allowed only to a version declared and verified compatible with the current schema; otherwise block the switch and use forward repair or an independent recovery destination.
- Production-like configuration checks must preserve explicit development/Mock mode needed by the current local preview.
- After contract approval, verify that spec-superflow state tooling is available and create a current execution plan. Do not start implementation without verifiable DP-3 state and a current plan.

## Execution Batches

1. **Isolation baseline:** Implement drill target types/rejection rules and remove fixed Compose resource names and dangerous database defaults. Exit: unsafe targets are rejected before writes; M4 resources are isolated from preview resources.
2. **Production-like configuration safety:** Implement credential and Provider validation. Exit: weak/default credentials and unsafe Mock combinations fail closed in production-like mode; development compatibility regression passes.
3. **Backup and integrity:** Define the manifest, coverage, archive, and verification. Exit: complete backups are verifiable; omissions, path traversal, or hash mismatches are rejected.
4. **Isolated restore and metrics:** Protect empty destinations, restore database/files, verify business behavior, and calculate RPO/RTO. Exit: restore cannot operate on source/unknown targets; missing evidence does not produce fabricated metrics.
5. **Integration, security, and degradation drills:** Run end-to-end recovery, idempotency, security-boundary, migration-compatibility, and manual-degradation tests. Exit: automation uses only isolated targets and mocked dependencies; manual checks are separately identified.
6. **Runbooks, regression, and acceptance report:** Align operational docs, run acceptance serially, and record evidence. Exit: AC-G1-AC-G5 mappings are complete, conclusions match logs, and uncovered items are explicit.

Use `tasks.md` for exact task boundaries and dependencies. Batches 1-4 follow their task dependencies; Batch 5 depends on Batches 2 and 4; Batch 6 depends on Batch 5. Pause dependent batches when a prerequisite fails.

## Test Obligations

- For each batch, run focused new/modified unit tests, then relevant existing regression tests. Run Batch 5/6 integration drills serially as defined in `tasks.md`.
- Verify rejection of preview databases, occupied volumes, source databases, non-empty unknown restore destinations, and paths outside the allowlist.
- Verify backup component coverage, manifest, hash tampering/omissions, secret exclusion, and fail-closed behavior.
- Verify configuration boundaries, migration upgrades/repeated upgrades, and compatible rollback rejection matrix; confirm no database downgrade occurs.
- Verify post-restore business checks, idempotency, manual workflows with AI disabled, fallback reconciliation during system-of-record failure, security, and audit boundaries.
- Verify normal, exceeded, and missing-evidence RPO/RTO cases. Final report status must be supported by observed evidence.
- Record actual test commands/results, environment and dataset size, redacted log locations, image/migration versions, RPO/RTO calculations, and the uncovered status of offsite/recurring/production capabilities.

## Review Gates

- **Batch gate:** After each batch, check requirement mapping, diff, and test evidence. Failed security/target-protection tests prohibit drill writes.
- **Integration gate:** Do not write final passing conclusions until isolated restore, business verification, idempotency, and degradation scenarios pass in a unique isolated project.
- **Close gate:** `m4-verification.md` must map each AC-G1-AC-G5 item to commands and evidence; unevidenced items remain uncovered. Complete the project's independent code review and closure workflow.

## Escalation / Rewind Conditions

- If preview data, real credentials, shared/production resources, or external services may be touched, stop and request scope clarification.
- If requirements cannot be mapped to a batch/test, implementation requires changing an approved interface/boundary, or PRD targets conflict, return to planning and update specs/design/tasks and this contract.
- If isolation targets cannot be identified reliably, Docker is unavailable, or consistent backup/restore evidence cannot be obtained, pause the affected batch and report the uncovered reason; do not bypass protections.
- If security, migration, recovery, or consistency tests fail, investigate and add regression coverage before dependent batches or passing claims.
- The legacy task headings have been normalized to spec-superflow v2 numbered checkbox lines only; task scope and acceptance criteria are unchanged. Workflow state, contract freshness, and execution-plan validity are verified through the installed spec-superflow runtime before implementation.

## Approval Gate (DP-3)

**User approval:** Approved in chat on 2026-10-20. The approved scope, safeguards, and test gates are the contents of this contract.

**Workflow state:** DP-3 approval is recorded in `changes/m4-resilience/.spec-superflow.yaml` from 2026-10-22. The planning-artifact format migration does not alter approved behavior or safeguards. Runtime implementation remains gated on a fresh state hash, current execution plan, and passing transition guard.
