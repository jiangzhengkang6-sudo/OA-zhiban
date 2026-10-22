"""Authorized task source loading used by the dedicated workbench."""
from ..services.authorization_service import require_business_identity


async def read_work_task_source(session, actor, source_type, source_id, source_version=None):
    from ..services.work_task_service import load_source
    actor = await require_business_identity(actor, session=session)
    return await load_source(session, actor, source_type, source_id, source_version)
