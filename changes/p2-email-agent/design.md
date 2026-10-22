# Email Design

EmailRecord stores tenant, owner, input/source snapshots, current status/version, redacted error and internal confirmation. EmailDraftVersion stores structured draft/checks/editor. AgentThread supplies task projection; immutable versions remain in dedicated business tables. Migration 0018 follows document migration 0017 and refuses nonempty downgrade.

The existing LLMFactory chooses deterministic mock or configured Ark structured output. Model calls are pure and bounded to 25 seconds while the business row is locked. Validation is inside the model recovery boundary; refreshed authorization and persistence are outside it. Failed model output pauses; failed business persistence rolls back. No exactly-once model-call claim is made after rollback.

Sources identify original lines; more than 300 lines become one bounded whole-body reference. Attachment data consists solely of name/sensitive metadata. The external-contact flag is user supplied rather than inferred from domains. Candidates include explicit needs_confirmation; no task is created.

Endpoints: POST/GET /api/emails, GET /api/emails/{id}, GET /{id}/versions, POST /{id}/analyze, POST /{id}/retry, PATCH /{id}/draft, POST /{id}/decisions. All mutations carry idempotency_key; review commands also require expected_version. Statuses: CREATED, DRAFT_READY, REVIEWING, PAUSED, CONFIRMED, REJECTED.

EmailView uses useDraftReview, draftCommands and DraftHistory shared with DocumentView. Attempt keys persist in sessionStorage by actor/scope/payload hash until a successful response. Route serials discard obsolete reads. Dirty drafts prevent commands and require acknowledgment before navigation/reload. Confirmation modals are followed by a fresh local version/state check.
