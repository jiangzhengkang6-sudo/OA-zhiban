# M4 Final Range Review

Date: 2026-10-22. Reviewer: current native executor; no reviewer subagent.

- Base: `8cb8fc625d3bb1c175f17cb0321e32837171a6b2`
- Head: `a1f7c706ce8074d5957815e3e4d46651b97d9764`
- Verdict: **fail - outstanding required verification**, not a failed recovery test.
- Receipt status: recording was attempted and rejected with `Final review requires an unambiguous recorded target branch`. This repository has only `codex/m1-identity-foundation` and no recorded isolation target/main/master. The range above is an explicit local review range, not a machine-certified target merge-base. No branch or provenance was fabricated to bypass the guard. Recover genuine target provenance before recording the final receipt; the code review report remains valid as a local inspection record.

## Findings

### Important: M4-FRONTEND-IMAGE - required container build has no passing evidence

`frontend/Dockerfile:8` requires `nginx:1.27-alpine`. The actual Docker build failed while resolving that image's Docker Hub metadata with `encountered unknown type text/html; children may not be fetched`; a retry failed again. Local frontend build and 119 tests passed but do not prove the container image builds. The approved upgrade/rollback requirement includes image build. Task 6.2 and AC-G5 remain partial, so final acceptance cannot pass. No old image, alternate base, or production deployment was used to conceal the gap.

Resolution: when registry metadata can be fetched, build the unchanged frontend Dockerfile, verify its artifact/runtime in a dedicated local environment, update task 6.2 and the verification report, then re-review the original complete range plus any fixes. Preserve this failed receipt; do not repeat identical failed review submissions.

No additional blocking code defect was found in the reviewed range. This statement does not convert the verification gap into a pass.

## Scope And Evidence

Reviewed the complete 27-file diff from base to head: production credential/target validation, Compose auth and managed files, isolated target execution, archive completeness/hash/path protection, independent empty restore, recovery metrics/CLI, integration/degradation/security/migration tests, runbooks and workflow evidence.

- 107 host unit regressions passed. Split database host/port/name cases first failed, then passed after the fail-closed fix. Default PostgreSQL port is normalized; separate credentials are permitted.
- Final Docker recovery test passed in 213.28 seconds. Embedded selected regression suite: 81 passed in 41.60 seconds. Login/history/attachment/approval/checkpoint/knowledge/audit/readiness checks and idempotent replay passed.
- Evidence: `data/m4-drills/evidence-6aeb180e9675`; RPO 2s, RTO 7s under the documented synthetic local conditions. Final backend image ID is recorded in `reviews/m4-verification.md`.
- Application rollback tested baseline backend source against schema `0029`, including read/write/approval/replay. Unknown or incompatible combinations are refused; database downgrade is not used.
- Native frontend build passed; 25 test files / 119 tests passed. Frontend image build failed as described above. `git diff --check` passed.

The code preserves explicit project/target validation before writes, rejects source/occupied/unknown restore destinations, checks component/path/hash integrity, excludes real environment configuration from drills, mocks external providers and retains atomic authorization/transaction boundaries. Operational documents restrict the CLI to local synthetic drills and avoid source database restore/cleanup.

## Provenance And Limits

Batch 1 already existed at the base commit. Its source snapshot was inspected as supplemental context; `reviews/batch1-review.md` records its original verification without a fabricated historical Git receipt. Only the actual base-to-head diff above is certified as the reviewed change range.

Prompt injection coverage is a deterministic authorization-gate regression, not comprehensive model red teaming. The backup uses static synthetic data, not concurrent production writes. RTO starts after the independent destination database is provisioned. Manual record signing/organization, real services, production capacity, HTTPS/network configuration, historical production images, offsite recovery and recurring backups are unverified.

No real `.env`, preview database, external message/model call, production resource, remote push or merge was used. User PRD files remain untracked. Delta spec publication and logical closure are deferred because required verification remains open; there is no archive authorization receipt.
