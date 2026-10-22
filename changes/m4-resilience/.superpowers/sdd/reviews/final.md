# M4 Final Range Review

Date: 2026-10-22. Reviewer: current native executor; no reviewer subagent.

- Base: `8cb8fc625d3bb1c175f17cb0321e32837171a6b2`.
- Implementation head: `9fe28dda555d0f3803547c042713597f861fcd7b`.
- Receipt head: the current HEAD recorded in the machine review JSON after this report and verification-state metadata are committed. It includes the implementation above and these review records; no later implementation change is certified by this statement.
- Verdict: **pass for the approved local synthetic scope**. No unresolved Critical/Important implementation finding was identified in the complete range. Production deployment and operational acceptance are outside this verdict.

## Previous Findings And Resolution

`01610ad` preserves the previous local failing report and the rejected receipt submission. No failed machine receipt existed: the target-branch guard rejected that submission before recording it.

**M4-FRONTEND-IMAGE resolved:** the configured registry mirror returned HTML for an nginx manifest. Exact-version Node/nginx images were explicitly pulled from a working mirror and their digests recorded. The existing Dockerfile builds successfully with `--pull=false`. No base-version substitution, global Docker modification or Docker restart was performed. Final image: `sha256:1514333a5b0683734a4892c16478632c177106a638bb02f5797dac488eb1ba86`.

The new HTTP check first exposed duplicate Content-Type headers at `/healthz`. `default_type text/plain` replaces the extra header. Rebuild and synthetic internal-network verification passed: health body and one header, root/SPA route, JavaScript/CSS assets and MIME types, GET query/header forwarding, POST body, backend 404, backend-outage 502 and independent static health. Temporary container/network cleanup was verified. This does not claim new browser interaction testing.

**Review target registration resolved prospectively:** at 2026-10-22T16:09:13+08:00, local `main` was newly created at the existing root baseline under the user's approved baseline-registration scope. See `reviews/git-baseline-provenance.md`. There was no historic main branch or isolation context; none is claimed. The plugin's legacy/manual single-trunk fallback now derives the complete merge-base. Current development remains on `codex/m1-identity-foundation`; no integration is authorized or performed.

## Scope And Evidence

Reviewed the original complete base-to-implementation range plus focused fixes: production database credentials/consistent target validation, Compose auth and managed files, isolated target execution, archive completeness/hash/path protection, independent empty restore, recovery metrics/CLI, integration/degradation/security/migration tests, frontend runtime configuration, repeatable smoke script, runbooks, canonical resilience spec and workflow evidence. Earlier range inspection was retained and extended; the range was not narrowed to the last commit.

- 107 host unit regressions passed. Database host/port/name mismatches failed before the fix and pass by rejection afterward. Default port normalization and separate credentials are covered.
- Final Docker recovery test: 1 passed / 213.28 seconds; 81 embedded selected regressions / 41.60 seconds. Login/history/attachments/approval/checkpoint/knowledge/audit/readiness and idempotent replay passed.
- Evidence: `data/m4-drills/evidence-6aeb180e9675`; measured local RPO 2s and RTO 7s. Exact timing, data volume and image IDs are in `reviews/m4-verification.md`.
- Baseline backend application rollback against schema `0029` passed read/write/approval/replay. Unknown/incompatible versions are refused. No database downgrade occurred.
- Frontend native build and 25 files / 119 tests passed; final container build and HTTP checks passed after the health-header correction. `git diff --check` passed.
- Explicit project/target validation precedes writes; source/occupied/unknown restore destinations are refused; component/path/hash completeness is checked; real configuration is excluded. CLI scope remains synthetic local data with external providers disabled/mocked.

## Nonblocking Follow-Up And Limits

Development dependency audit reports 6 findings (3 moderate, 1 high, 2 critical) in Vite/Vitest and their transitive tooling. Production dependency audit reports zero. The runtime stage contains nginx and static output, not Node development/test services. Track a separately tested tooling upgrade; this review does not certify all development dependencies or base-image vulnerability scanning. Do not expose development/test servers externally.

Batch 1 already existed at the base commit. Its snapshot and `reviews/batch1-review.md` were inspected as supplemental context; no historical pre-baseline diff or review receipt is fabricated. The machine receipt certifies only the actual base-to-head range.

Prompt-injection coverage tests deterministic authorization gates, not comprehensive model red teaming. Backup data is static and synthetic. Recovery timing starts with the independent destination DB already provisioned. Real services/models/scanner, organizational manual drills, HTTPS/network controls, production capacity, historical production images, concurrent backup consistency, encrypted offsite recovery and recurring backups remain unverified.

No real `.env`, preview database, external business message/model call, production resource, push or merge was used. User PRDs remain untracked. Canonical resilience specs were synchronized while executing. Archive authorization is not inferred; local branch delivery is complete independently of later archive/integration decisions.
