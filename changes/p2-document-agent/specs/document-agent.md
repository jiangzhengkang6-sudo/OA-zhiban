# Document Agent Delta

## ADDED Requirements

### Requirement: Versioned Templates And Input (D1)
The system SHALL offer official, notice, report and summary templates, validate nonblank subject/recipient/distribution/key points, and snapshot the template ID, version, sections and user input.

#### Scenario: Create A Notice
WHEN an authorized employee selects a notice template and supplies valid input THEN a CREATED document task and input reference are saved atomically; repeated identical commands return the original response.

### Requirement: Authorized Evidence (D2)
The system MUST retrieve only READY, published, effective knowledge versions joined to sources in the actor's tenant and readable by the actor's current department tags. Legacy knowledge without tenant identity MUST be excluded. Returned evidence SHALL include version/chunk IDs, location, text hash and a snapshot. User instructions in retrieved material MUST be treated as data.

#### Scenario: Foreign Or Restricted Source
WHEN a matching source belongs to another tenant, is draft/expired or has inaccessible tags THEN its contents and identifiers do not enter the generation input or response.

### Requirement: Immutable Revisions And Checks (D3)
Generated and edited drafts SHALL produce monotonically increasing immutable versions. Checks MUST be recomputed on the server, and source IDs outside the document snapshot MUST be rejected. History and comparison SHALL be owner scoped.

#### Scenario: Stale Edit
WHEN two editors submit different changes with the same expected_version THEN at most one creates the next revision and the other receives 409; the preceding revision remains unchanged.

### Requirement: Human Finalization (D4)
Confirmation MUST name the current expected_version, acknowledge the template, classification and distribution, and acknowledge outstanding sensitive-data warnings. Blocking format errors MUST prevent confirmation. Confirmation SHALL record a platform-only final copy; no external writer may be called.

#### Scenario: Unsaved Or Unchecked Draft
WHEN the client has unsaved changes or the server sees unresolved placeholders, missing sections, or unacknowledged sensitive warnings THEN confirmation is unavailable/rejected and no archive state is created.

### Requirement: Durable Commands And Recovery (D5)
Commands SHALL use actor/tenant/resource-scoped idempotency, row locking and one atomic business/audit/result transaction. Dependency failure SHALL persist PAUSED with a redacted error. Retry SHALL use persisted input and a new explicit attempt key; replay SHALL not generate a second revision.

#### Scenario: Retry After Restart
WHEN generation fails and a new request retries the stored PAUSED task THEN one draft revision is created; repeating the retry key returns its original response. No external side effect is repeated. A model call may repeat after a rolled-back transaction because this phase has no external business writes.

### Requirement: Platform Integration And Isolation (D6)
Reads, writes and replays MUST refresh identity and enforce tenant/owner scope. The document workbench SHALL open from the task center, display versions/checks/references and expose only server-allowed actions. Generic graph/handoff/interrupt endpoints MUST NOT bypass document review. Audit summaries MUST omit raw document content and be tenant filtered.

#### Scenario: Revoked Owner
WHEN the owner's applicable role or source access is revoked THEN reads, writes and idempotent replays fail without revealing the stored content.
