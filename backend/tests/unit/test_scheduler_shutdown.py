import asyncio

from app.main import close_scheduler


async def test_shutdown_cancels_blocked_scan_and_runs_its_cleanup():
    started, cleaned, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def scan():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    task = asyncio.create_task(scan())
    await started.wait()
    await asyncio.wait_for(close_scheduler(task, stop, timeout=.01), timeout=1)
    assert stop.is_set() and cleaned.is_set() and task.cancelled()


async def test_shutdown_allows_cooperative_scan_to_finish():
    stop = asyncio.Event()
    task = asyncio.create_task(stop.wait())
    await close_scheduler(task, stop)
    assert task.done() and not task.cancelled()
