# Email Agent Delta

## ADDED Requirements

### E1: Owned Input And Evidence
The system SHALL validate nonblank subject, sender, recipients and body, bounded attachment metadata, and snapshot input with server-issued source references and hashes. Only the authenticated tenant and owner may read body, draft, history or replay results.

Scenario: other-owner or foreign-tenant reads/commands do not disclose stored mail. Refreshed role revocation also denies access.

### E2: Structured Analysis And Immutable Revisions
The system SHALL produce category, priority, summary, action candidates and reply subject/body. Generated and edited drafts MUST append immutable versions. Every draft/action reference MUST belong to stored evidence. Model output failures MUST enter durable PAUSED; user edit validation errors MUST reject without a revision.

Scenario: invented model evidence pauses without a saved draft. A stale expected_version returns 409 and preserves history.

### E3: Explicit Human Confirmation
Confirmation MUST use the saved version, metadata acknowledgment and acknowledgment of warning checks. External-contact or sensitive attachment metadata MUST require secondary_confirmed. Client unsaved edits MUST disable confirmation. Terminal versions MUST reject new edits or regeneration.

Scenario: dismissing the secondary modal sends no decision. Confirmation creates an internal record with external_writes=false and no mail, file, task or calendar transport invocation.

### E4: Recovery And Atomic Commands
Commands MUST claim actor/tenant/resource-scoped idempotency and lock business rows. Business state, audit and completed command result MUST commit together. A model failure SHALL return a redacted PAUSED result; a new explicit retry key SHALL recover stored input. Persistence errors MUST roll back rather than masquerade as model failures. Identity MUST be rechecked after model await on success and failure.

Scenario: identical retry replay returns the original result without a duplicate revision. Failed regeneration retains the earlier saved version. Rolled-back persistence permits the same command to execute again.

### E5: Platform Controls
The workbench SHALL provide loading/error/empty/terminal states, version comparison, route protection for unsaved edits and task-center navigation. Policy and degradation SHALL gate fresh commands. Generic thread messages, interrupt resume and task retry/handoff MUST NOT bypass email confirmation. Audits MUST omit raw body and be tenant filtered; other-owner admin task summaries MUST have no action permissions.

Scenario: role-revoked task lists omit document/email rows. A disabled scene rejects new commands while an authorized completed-key replay remains idempotent.
