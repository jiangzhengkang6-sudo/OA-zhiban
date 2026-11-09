"""Serve the configured local application without scanning unrelated work queues."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def paused_scheduler(stop_event):
    await stop_event.wait()


if __name__ == '__main__':
    import uvicorn
    import app.main as application

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8015)
    options = parser.parse_args()
    # Preserve the normal schema, configuration and graph startup checks.
    # Only this local verification process pauses scheduled side effects.
    application.run_scheduler = paused_scheduler
    server = uvicorn.Server(uvicorn.Config(application.app, host='127.0.0.1',
        port=options.port, log_level='warning', loop='none'))
    if sys.platform == 'win32':
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())
