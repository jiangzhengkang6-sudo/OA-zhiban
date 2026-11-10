"""
OA 智能体管理系统 - 接口依赖模块。

提供 FastAPI 路由层需要的共享依赖，如当前登录用户解析（get_current_user）与角色校验
（require_roles）。认证由 AuthMiddleware 完成解析并注入 contextvars，本模块仅做读取与校验。
"""

from ..core.context import CurrentUser, get_current_user as _ctx_user
from ..core.errors import AppException, ErrorCode
from ..services.authorization_service import require_fresh_identity
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.session import get_db


async def get_current_user(request: Request, session: AsyncSession = Depends(get_db)) -> CurrentUser:
    """依赖：获取当前登录用户，未认证时抛 401。

    Returns:
        CurrentUser: 当前用户。

    Raises:
        AppException: 未认证时。
    """
    user = _ctx_user()
    if user is None:
        raise AppException(
            ErrorCode.UNAUTHORIZED, "未登录或凭证无效", http_status=401
        )
    user = await require_fresh_identity(user, session=session)
    from ..core.config import get_settings
    path = request.url.path.removeprefix(get_settings().api_prefix).strip('/')
    if path.split('/')[0] not in {'oa', 'organization', 'meeting-events', 'public-mail'}:
        from ..services.authorization_service import require_ai_enabled
        require_ai_enabled()
    if user.data_scope.get('identity_provider') == 'builtin':
        from ..services.authorization_service import require_permission
        from ..core.config import get_settings
        path = request.url.path.removeprefix(get_settings().api_prefix + '/')
        prefix = path.split('/')[0]
        if prefix in {'admin', 'agent'}:
            prefix = path.split('/')[1] if '/' in path else ''
        # 统一助手按具体业务卡片分别授权，不能因缺少某个模块权限而拒绝整个总览。
        if prefix == 'assistant-v2':
            return user
        # Each formal route below has a separate permission check and service boundary.
        formal = {'/oa/workflows': 'workflow','/oa/leaves':'leave','/oa/balances':'leave_balance',
                  '/oa/approvals':'approval','/oa/administration':'workflow_admin','/oa/reimbursements':'reimbursement'}
        if path=='oa/delegations' or path.startswith('oa/delegations/'):
            require_permission(user,'approval','read' if request.method in {'GET','HEAD'} else 'write')
            return user
        if path=='oa/announcements' or path.startswith('oa/announcements/'):
            action='read' if request.method in {'GET','HEAD'} or request.method=='POST' and path.count('/')==3 and path.endswith('/read') else 'write'
            require_permission(user,'announcement',action)
            return user
        if path=='oa/work-items' and request.method=='GET':
            permissions=user.data_scope.get('permissions',[])
            resources={'approval','work_task'} if get_settings().ai_enabled else {'approval'}
            if not any(p['resource'] in resources and p['action']=='read' for p in permissions):
                raise AppException(ErrorCode.FORBIDDEN,'当前账号没有待办读取权限',http_status=403)
            return user
        if path=='oa/notifications' or path.startswith('oa/notifications/'):
            action='read' if request.method in {'GET','HEAD'} else 'write'
            resource='notification'
            if path=='oa/notifications/deliveries' or path.startswith('oa/notifications/deliveries/'):
                resource='notification_admin'
            if path.startswith('oa/notifications/contacts/') and path.removeprefix('oa/notifications/contacts/')!=user.user_id:
                resource='notification_admin'
            require_permission(user,resource,action)
            return user
        if path=='oa/tickets' or path.startswith('oa/tickets/'):
            action='read' if request.method in {'GET','HEAD'} else 'write'
            if path=='oa/tickets/rules':
                require_permission(user,'ticket_admin',action)
            elif path.endswith('/handle') or path=='oa/tickets' and request.query_params.get('handling')=='true':
                require_permission(user,'ticket_handle',action)
            elif path.count('/')==2 and action=='read' and not path.startswith('oa/tickets/results'):
                if not any(p['resource'] in {'ticket','ticket_handle'} and p['action']=='read' for p in user.data_scope.get('permissions',[])):
                    raise AppException(ErrorCode.FORBIDDEN,'当前账号没有工单查看权限',http_status=403)
            else:
                require_permission(user,'ticket',action)
            return user
        if path == 'oa/workflows/options' and request.method == 'GET':
            if not any(any(p['resource']==r and p['action']=='read' and p['scope']=='department' for p in user.data_scope.get('permissions',[]))
                       for r in ('workflow','leave_balance','workflow_admin')):
                raise AppException(ErrorCode.FORBIDDEN, '当前账号没有部门管理权限', http_status=403)
            return user
        if request.url.path.removeprefix(get_settings().api_prefix) == '/oa/workflows' and request.method == 'GET' and request.query_params.get('available') == 'true':
            scene=request.query_params.get('scene','leave')
            if scene not in {'leave','reimbursement'}:
                raise AppException(ErrorCode.FORBIDDEN,'未知业务场景',http_status=403)
            require_permission(user, scene, 'read')
            return user
        formal_path = request.url.path.removeprefix(get_settings().api_prefix)
        for route, formal_resource in formal.items():
            if formal_path == route or formal_path.startswith(route + '/'):
                require_permission(user, formal_resource, 'read' if request.method in {'GET','HEAD'} else 'write')
                return user
        resources = {'organization': 'organization', 'meetings': 'meeting', 'meeting-events':'meeting',
            'meeting-transcriptions':'meeting', 'documents': 'document',
            'emails': 'email', 'public-mail': 'email', 'work-tasks': 'work_task', 'reports': 'report', 'contracts': 'contract',
            'threads': 'thread', 'tasks': 'task', 'knowledge': 'knowledge', 'audit': 'audit',
            'audit-exports': 'audit', 'agent-policies': 'policy', 'agent-policy-versions': 'policy',
            'readiness': 'operations', 'operations': 'operations', 'degradation': 'operations'}
        if prefix == 'interrupts':
            require_permission(user, 'thread', 'write')
            return user
        if prefix in {'leaves', 'approvals', 'tickets', 'support'}:
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '本阶段尚未接通正式 OA 业务，请等待后续业务阶段', http_status=503)
        resource = resources.get(prefix)
        if resource in {'operations'}:
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '此管理模块尚未完成正式组织权限隔离，请使用后续正式化版本', http_status=503)
        if resource is None:
            raise AppException(ErrorCode.FORBIDDEN, '接口尚未配置正式权限', http_status=403)
        try:
            # Admission issues viewer credentials; the service still checks invitation and state.
            video_admission = (prefix == 'meeting-events' and request.method == 'POST'
                               and path.count('/') == 2 and path.endswith('/video-session'))
            require_permission(user, resource, 'read' if request.method in {'GET','HEAD'} or video_admission else 'write')
        except AppException:
            from ..services.identity_service import audit
            audit(session, user.user_id, 'identity.denied', resource, result='fail')
            await session.commit()
            raise
    return user


def require_roles(*roles: str):
    """构造角色校验依赖（装饰器工厂）。

    Args:
        *roles: 允许的角色列表。

    Returns:
        callable: 校验当前用户是否具备任一角色的依赖函数。
    """

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(r in user.roles for r in roles):
            raise AppException(
                ErrorCode.FORBIDDEN, "无权限执行此操作", http_status=403
            )
        return user

    return _dep


async def require_audit_access(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    # Builtin requests already checked explicit resource/action permissions above.
    if user.data_scope.get('identity_provider') != 'builtin' and 'admin' not in user.roles:
        raise AppException(ErrorCode.FORBIDDEN, '无权限执行此操作', http_status=403)
    return user
