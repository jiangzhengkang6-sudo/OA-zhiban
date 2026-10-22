# Email Implementation Scope

User authorization on 2026-10-14: skip the unavailable ssf gate and finish documents and email together. No further start approval is required. This document does not assert generated decision points, a commit range or machine receipts.

Implementation uses the existing FastAPI/SQLAlchemy/PostgreSQL and Vue/Element Plus stack. Add only email_record and email_draft_version in 0018; document tables belong to 0017. Preserve existing untracked changes. Validate destructive test targets as oa_agent_test; never truncate oa_agent.

E1/E2 map to schemas, sources, generator and revision service. E3 maps to server decisions and workbench confirmation gates. E4 maps to idempotency, locking, recovery, transaction and midflight identity tests. E5 maps to task/thread/interrupt/audit/policy/degradation integration and frontend regressions.

Batches: domain/contracts; persisted API; integrated workbench; review/regression/acceptance evidence. Verification is combined with changes/p2-document-agent/reviews/verification.md and document-email-review.md. External mail delivery and attachment handling are excluded; adding these requires a separate concrete integration scope.
