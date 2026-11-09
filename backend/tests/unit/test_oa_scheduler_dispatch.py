from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest


@pytest.mark.parametrize('provider',['builtin','mock'])
@pytest.mark.parametrize('ai_enabled',[True,False])
async def test_scheduler_tick_selects_matching_business_authority(monkeypatch,provider,ai_enabled):
    from app.services import scheduler,oa_workflow_scheduler,work_task_scheduler,oa_notification_service,oa_notification_worker
    session=SimpleNamespace(commit=AsyncMock())
    @asynccontextmanager
    async def factory(): yield session
    monkeypatch.setattr(scheduler,'get_settings',lambda:SimpleNamespace(auth_provider=provider,ai_enabled=ai_enabled,scheduler_interval_seconds=1,business_scheduler_enabled=True))
    monkeypatch.setattr(scheduler,'async_session_factory',factory)
    formal=AsyncMock(return_value={'errors':[]})
    legacy=AsyncMock()
    notifications=AsyncMock()
    delivery=AsyncMock()
    monkeypatch.setattr(oa_notification_service,'dispatch',notifications)
    monkeypatch.setattr(oa_notification_worker,'run_once',delivery)
    monkeypatch.setattr(oa_workflow_scheduler,'scan',formal)
    monkeypatch.setattr(work_task_scheduler,'scan_overdue',legacy)
    monkeypatch.setattr(scheduler,'_tick',AsyncMock())
    import asyncio
    stop=asyncio.Event()
    async def done(): stop.set()
    session.commit.side_effect=done
    if provider=='mock' and not ai_enabled:
        stop.set()
        # Run one iteration; the timeout wait ends the otherwise idle loop.
        stop.clear()
        async def wait(): stop.set()
        monkeypatch.setattr(stop,'wait',wait)
    await scheduler.run_scheduler(stop)
    assert formal.await_count==(1 if provider=='builtin' else 0)
    assert legacy.await_count==(1 if provider=='builtin' or provider=='mock' and ai_enabled else 0)
    assert scheduler._tick.await_count==(1 if provider=='mock' and ai_enabled else 0)
    assert notifications.await_count==0
    assert delivery.await_count==0


async def test_notification_worker_does_not_resume_business_or_smtp(monkeypatch):
    from app.services import scheduler, oa_notification_service, oa_notification_worker, oa_workflow_scheduler, work_task_scheduler
    session=SimpleNamespace(commit=AsyncMock())
    @asynccontextmanager
    async def factory(): yield session
    monkeypatch.setattr(scheduler,'async_session_factory',factory)
    notifications, delivery, business, tasks = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(oa_notification_service,'dispatch',notifications)
    monkeypatch.setattr(oa_notification_worker,'run_once',delivery)
    monkeypatch.setattr(oa_workflow_scheduler,'scan',business)
    monkeypatch.setattr(work_task_scheduler,'scan_overdue',tasks)
    await scheduler.notification_tick(SimpleNamespace(auth_provider='builtin',notification_wecom_worker_enabled=True,notification_smtp_worker_enabled=False))
    notifications.assert_awaited_once()
    assert [call.kwargs['channel'] for call in delivery.await_args_list] == ['wecom']
    business.assert_not_awaited()
    tasks.assert_not_awaited()
