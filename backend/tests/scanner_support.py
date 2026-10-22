"""Loopback ClamAV protocol peer; never substitute this for a live AV engine."""
import asyncio
from contextlib import asynccontextmanager
import struct


@asynccontextmanager
async def scanner_server(response=b'stream: OK\0', *, delay=0):
    requests = []
    tasks = set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            command = await reader.readexactly(10)
            chunks = []
            while size := struct.unpack('!I', await reader.readexactly(4))[0]:
                assert size <= 65536
                chunks.append(await reader.readexactly(size))
            content = b''.join(chunks)
            requests.append(dict(command=command, chunks=chunks, content=content))
            if delay:
                await asyncio.sleep(delay)
            reply = response(content) if callable(response) else response
            writer.write(reply)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            tasks.discard(task)

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    try:
        yield server.sockets[0].getsockname()[1], requests
    finally:
        server.close()
        await server.wait_closed()
        pending = list(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
