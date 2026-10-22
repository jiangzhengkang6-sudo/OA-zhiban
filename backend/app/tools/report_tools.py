"""Fixed report tool boundary, with fresh authority and no model SQL input."""
from ..schemas.report import ReportPlan
from ..services.authorization_service import require_business_identity
from ..services import report_query


async def run_registered_report_query(actor, plan):
    actor = await require_business_identity(actor)
    from ..services.authorization_service import require_permission
    require_permission(actor, 'report', 'read')
    plan = ReportPlan.model_validate(plan)
    report_query.scope_fingerprint(actor, plan.scope)
    return await report_query.execute_plan(actor, plan)
