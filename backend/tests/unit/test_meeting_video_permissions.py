from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.api import deps
from app.core.context import CurrentUser
from app.core.errors import AppException


@pytest.mark.parametrize('path,allowed', [
    ('/api/meeting-events/meeting-id/video-session', True),
    ('/api/meeting-events/meeting-id/start', False),
    ('/api/meeting-events/meeting-id/end', False),
    ('/api/meeting-events/meeting-id/nested/video-session', False),
])
async def test_video_admission_uses_read_permission_without_granting_edit(monkeypatch, path, allowed):
    actor = CurrentUser(user_id='member', tenant_id='tenant', data_scope={
        'identity_provider': 'builtin',
        'permissions': [{'resource': 'meeting', 'action': 'read', 'scope': 'self'}],
    })
    monkeypatch.setattr(deps, '_ctx_user', lambda: actor)
    monkeypatch.setattr(deps, 'require_fresh_identity', AsyncMock(return_value=actor))
    from app.services import identity_service
    monkeypatch.setattr(identity_service, 'audit', lambda *args, **kwargs: None)
    db = AsyncMock()
    request = Request({'type': 'http', 'method': 'POST', 'path': path, 'headers': []})

    if allowed:
        assert await deps.get_current_user(request, db) is actor
    else:
        with pytest.raises(AppException) as error:
            await deps.get_current_user(request, db)
        assert error.value.http_status == 403
