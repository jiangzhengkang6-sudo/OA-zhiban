"""Run separately from the backend so application/DB outages can still alert."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings
from app.ops.operations_monitor import tick


async def run(once=False):
    settings = get_settings()
    while True:
        try:
            state = await tick(settings)
            failures = sum(c['status'] == 'FAIL' for c in state['checks'])
            print(f'巡检完成；故障项={failures}', flush=True)
        except Exception:
            # No exception/URL/credential/body logging, including file corruption.
            print('巡检未完成；请检查状态文件、进程锁及本机权限', file=sys.stderr, flush=True)
            if once:
                return 2
        else:
            if once:
                return 1 if failures else 0
        await asyncio.sleep(settings.ops_poll_seconds)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args.once)))
    except KeyboardInterrupt:
        pass
