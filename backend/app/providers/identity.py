"""Identity authority is configured independently of the OA business provider."""
from ..core.config import get_settings
from ..core.context import CurrentUser
from ..core.errors import AppException, ErrorCode


class IdentityResolver:
    async def resolve(self, user_id, *, session):
        settings = get_settings()
        if settings.auth_provider == 'builtin':
            from ..models.identity import OAUser
            from ..services.identity_service import current_identity
            return await current_identity(session, await session.get(OAUser, user_id, populate_existing=True))
        if settings.auth_provider == 'mock':
            from ..adapters.factory import get_adapter
            context = get_adapter().get_user_context(user_id)
            if context:
                return CurrentUser(user_id=context.user_id, tenant_id=context.tenant_id,
                    roles=list(context.roles), depts=[context.dept_id], data_scope=context.data_scope)
        raise AppException(ErrorCode.UNAUTHORIZED, '身份无效或已停用', http_status=401)
