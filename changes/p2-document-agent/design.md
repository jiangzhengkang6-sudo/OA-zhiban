# Document Agent Design

## Context

FastAPI/SQLAlchemy/PostgreSQL and Vue/Element Plus already provide owner-scoped meeting commands, shared idempotency and audit services, policy/degradation controls and a task center. The repository has no commits and the optional ssf scripts are absent. The original correcting thread is finished; source work happens in E:/OA AGENT SYSTEM on codex/p2-meeting-agent.

## Goals

Provide a complete internal drafting and human-review workflow while retaining source/template identity and immutable revisions. Preserve prior scene behavior and test only against oa_agent_test.

## Decisions

1. Choice: DocumentRecord stores input/template/evidence and task state; DocumentDraftVersion stores immutable content/references/checks and editor. Rationale: match established business-table ownership and revision patterns. Alternatives: overwriting one body loses history; reusing KnowledgeDocument mixes drafts with published retrieval material.
2. Choice: use database commands for this internal pure-generation phase, not the shared LangGraph draft field. Rationale: isolate document review from meeting/leave graph routes and preserve atomic command results. Alternatives: a new graph can follow when external publication introduces checkpoints and reconciliation. This phase can repeat pure model calls after a DB rollback and makes no exactly-once model-call claim.
3. Choice: static, versioned templates and deterministic offline drafting; configured Ark uses existing LLMFactory structured output. Rationale: retain offline development and avoid a second provider layer. Alternatives: editable template governance and attachment parsing are later capabilities.
4. Choice: retrieve versioned knowledge with explicit source tenant and department ACL filters; save snapshot metadata and recheck current source access on every document read/write/replay. Rationale: the existing legacy search lacks a tenant identifier. Alternatives: global knowledge search risks cross-tenant material reuse.
5. Choice: source references come from the server's input/evidence snapshots. Server format checks require headings and forbid unresolved placeholders; basic sensitive-pattern checks require an explicit warning acknowledgment. Rationale: warnings are advisory and never legal/comprehensive DLP certification.
6. Choice: row lock + expected_version + scoped idempotency; confirm archives only current content plus frozen metadata. Rationale: prevent concurrent edits and transport retries from changing the approved version. No publication endpoint exists.

## Interfaces

GET /api/documents/templates; POST/GET /api/documents; GET /api/documents/{id}; POST /{id}/generate, /retry; PATCH /{id}/draft; POST /{id}/decisions; GET /{id}/versions. Decision actions: confirm/reject/regenerate. Every command has idempotency_key; every post-generation mutation has expected_version. Confirm also has metadata_confirmed and warnings_acknowledged.

Document statuses: CREATED, DRAFT_READY, REVIEWING, PAUSED, CONFIRMED, REJECTED. AgentThread projection: DRAFT, WAITING_HUMAN, PAUSED, COMPLETED, REJECTED. Document APIs enforce owner scope even for admins; admin task summaries contain no draft material or edit actions for other owners.

## Risks And Trade-Offs

Pure generation holds the record lock and uses a bounded timeout. A DB rollback may repeat a model call but cannot repeat publication. Knowledge snapshots are private document evidence, not a new knowledge publication. Pattern checks cover basic contact/identity/token patterns and do not certify classification. P2 email is implemented alongside this change under the user's subsequent authorization, with its own scope record. External OA integrations and manual acceptance remain outstanding.
