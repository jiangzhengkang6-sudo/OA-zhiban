# P2 Document Agent

## Why

The meeting-text capability is already implemented. The next PRD capability is document drafting (F-052/F-053), with recoverable commands (F-055). Employees currently cannot create a template-based draft, inspect its material references, save revisions, or confirm a final internal copy in this platform.

## What Changes

Add a document workbench for official documents, notices, reports and summaries. Capture a versioned template, subject, recipient, deadline, basis, key points, classification and distribution. Generate a draft, retain immutable revisions, run format and sensitive-data checks, compare revisions, and explicitly confirm an internal archive copy.

## Scope

### In Scope

Platform-local drafting, published tenant-scoped knowledge references, immutable source snapshots, version comparison, human edits, rejection, regeneration, dependency-failure retry, owner-only access, fresh authorization, command replay, task projection and redacted audit.

### Out of Scope

External publication, sealing, OA archive writes, email delivery, legal validation of official-document formatting, arbitrary template administration, file export and legacy knowledge without tenant identity. The user subsequently authorized implementing P2 email alongside this change; its local scope is recorded in changes/p2-email-agent. Meeting manual acceptance remains independent.

## Impact

New document models, additive migration 0017, schema/service/router, Vue view/API/types and tests. Integrate the existing task/audit/policy/degradation surfaces without rerouting FAQ, leave, ticket or meeting graphs.

## Capabilities

F-052: authorized evidence and template/source version traceability. F-053: basic format checks, revision comparison and manual finalization, with external publication deferred. F-055: durable database state and replay-safe internal commands; generation is pure and can be retried after a rollback.

## Authorization And Tooling

User request on 2026-10-14: continue P2 development directly after the original thread finishes. This change records the concrete implementation scope of that request. It does not claim approval of an ssf-generated contract or machine receipts. The installed skills lack their referenced ssf scripts; use repository-local test/review evidence. No commits exist in the current repository, so there is no valid base/head SHA range.
