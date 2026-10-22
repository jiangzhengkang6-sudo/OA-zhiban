# B5 Task 5.1 ticket operations review — 2026-10-13

## Scope

内置权威工单、重复候选与显式合并、版本化分派规则、分派缺失降级和资源授权。

## Evidence

- RED: 新增 `test_ticket_operations.py` 首次收集失败，因为权威工单模型尚不存在。
- GREEN: Task 5.1 focused tests `4 passed`。
- Regression: backend API/migration/unit/graph suite `154 passed in 73.47s`。
- Migration head advanced non-destructively to `0008_support_ticket_operations`.

## Verified behavior

- Confirmed ticket writes persist `TicketRecord` and apply the highest-priority matching assignment rule.
- Similar open/in-progress tickets return deterministic duplicate candidates; creation does not silently merge.
- Explicit merge is tenant/owner scoped and idempotent.
- Missing assignment rules leave the ticket open and unassigned with a structured `NO_ASSIGNMENT_RULE` reason.
- Authoritative ticket reads allow the owner, support role, or administrator and reject unrelated users.
- The existing assistant confirmation path now uses the same authoritative service.

## Assessment

Task 5.1 passes review. Task 5.2 remains the next implementation slice.
