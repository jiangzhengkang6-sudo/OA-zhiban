# P2 Document Implementation Scope

## Intent Lock

Continue P2 after the original correcting thread completes, implementing PRD document drafting as a platform-local workflow. User explicitly requested direct development on 2026-10-14. No new external-system write is authorized or implemented.

## Behavior And Coverage

D1 templates/input -> Batch 1/2/3; D2 tenant/permission/published evidence -> Batch 2; D3 immutable versions/checks -> Batch 1/2/3; D4 explicit version/metadata/warning confirmation -> Batch 1/2/3; D5 replay/PAUSED/retry -> Batch 2; D6 tasks/ACL/redacted audit/generic-route guards -> Batch 2/3/4. No unmapped requirement.

## Scope Fence

Exclude OA publication, stamping, external archive, sending mail, legal format certification, template management and attachment export. On 2026-10-14 the user explicitly authorized skipping the unavailable ssf gate and finishing document drafting and email together. Email implementation is recorded in changes/p2-email-agent and shares command/UI integration and verification with this change. Preserve existing meeting/P1 functionality and leave meeting human acceptance outstanding.

## Constraints

Use current stack and existing auth/idempotency/audit/policy services. Two additive document tables (0017), plus two additive email tables (0018) under the combined authorization. Never truncate oa_agent; database tests require explicitly validated oa_agent_test. Keep all existing untracked user files. Work on existing codex/p2-meeting-agent because the original thread is finished and Git has no commits to create a useful isolated worktree.

## Batches And Review

Domain -> persisted API -> workbench -> broad verification, sequential dependencies. Each behavior gets a failing test before implementation, followed by focused verification and boundary review. Review must cover tenant/owner checks, snapshot/source authority, stale versions, replay, generic-route bypasses, terminal state, confirmation metadata and zero external writes.

## Tooling And Approval Evidence

This is a repository-local scope record under the user's direct-development instruction, not an ssf approval or execution receipt. The referenced ssf scripts/templates are absent and no commit range exists; do not generate fake DP records or SHA receipts. Do not infer the meeting contract authorizes documents. Manual tests and review reports must distinguish completed development from manual/production acceptance.

## Rewind Conditions

External writes, a second provider layer, new approval roles, cross-owner visibility of document content, legal-format guarantees or template-governance scope require a new scope decision. A failing ACL/replay/transaction test blocks dependent work until repaired.
