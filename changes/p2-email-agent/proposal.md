# P2 Email Agent

## Purpose And Authorization

Implement F-054 and the platform-local part of F-055 from the formal PRD. On 2026-10-14 the user explicitly requested document drafting and email development together and approved skipping the unavailable ssf gate. This is a scope record, not a generated approval receipt.

## Delivery

Employees enter mail subject, sender, recipients, text, external-contact flag and attachment metadata. The system generates classification, priority, summary, evidence-linked task candidates and a reply draft. Users can revise, compare, reject, regenerate, retry and confirm a specific saved version. External contacts or sensitive attachment metadata require an additional confirmation.

## Boundary

Confirmation stores an internal record. Mailbox synchronization, send/reply/forward transports, attachment bytes, OCR, real tasks/calendar and external OA writes are outside this delivery. Classification and sensitive warnings are advisory. Actual Ark semantic quality and human business acceptance remain separate.

## Impact

Two additive tables in migration 0018, email schemas/generator/service/router, Vue workbench, shared document/email command handling, task/navigation/audit/policy/degradation integration and tests. Existing meeting and P1 features remain in regression scope.
