"""Bounded ClamAV INSTREAM adapter; only an explicit OK means CLEAN."""
import asyncio
import struct

from ..core.config import get_settings


async def scan_bytes(content: bytes) -> str:
    settings = get_settings()
    if not settings.clamd_host:
        return 'PENDING'
    try:
        async with asyncio.timeout(settings.attachment_scan_timeout_seconds):
            reader, writer = await asyncio.open_connection(settings.clamd_host, settings.clamd_port)
            try:
                writer.write(b'zINSTREAM\0')
                for start in range(0, len(content), 65536):
                    chunk = content[start:start + 65536]
                    writer.write(struct.pack('!I', len(chunk)) + chunk)
                    await writer.drain()
                writer.write(struct.pack('!I', 0))
                await writer.drain()
                response = (await reader.readuntil(b'\0')).decode('utf-8', errors='replace').strip('\0\r\n')
                if response == 'stream: OK':
                    return 'CLEAN'
                if response.startswith('stream: ') and response.endswith(' FOUND'):
                    return 'INFECTED'
                return 'ERROR'
            finally:
                writer.close()
                await writer.wait_closed()
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return 'ERROR'
