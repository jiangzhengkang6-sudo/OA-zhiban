import asyncio
import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.ops.attachment_scanner import verify_scanner
from app.providers import file_scanner
from tests.scanner_support import scanner_server


def configured(port):
    return Settings(_env_file=None, clamd_host='127.0.0.1', clamd_port=port,
                    attachment_scan_timeout_seconds=1)


@pytest.mark.parametrize('reply,outcome', [
    (b'stream: OK\0', 'CLEAN'),
    (b'stream: Eicar-Signature FOUND\0', 'INFECTED'),
    (b'stream: size limit exceeded. ERROR\0', 'ERROR'),
    (b'OK\0', 'ERROR'),
    (b'stream: OK extra\0', 'ERROR'),
    (b'stream: OK', 'ERROR'),
    (b'', 'ERROR'),
    (b'x' * 66000 + b'\0', 'ERROR'),
], ids=['clean', 'infected', 'engine-error', 'unqualified-ok', 'extra-text', 'truncated', 'empty', 'overlong'])
async def test_instream_protocol_and_fail_closed_responses(reply, outcome):
    content = b'\x00\x01\xff' * 50000
    async with scanner_server(reply) as (port, requests):
        assert await file_scanner.scan_bytes(content, settings=configured(port)) == outcome
    assert requests[0]['command'] == b'zINSTREAM\0'
    assert requests[0]['content'] == content
    assert len(requests[0]['chunks']) == 3


async def test_empty_stream_is_terminated():
    async with scanner_server() as (port, requests):
        assert await file_scanner.scan_bytes(b'', settings=configured(port)) == 'CLEAN'
    assert requests[0]['content'] == b'' and requests[0]['chunks'] == []


async def test_timeout_is_bounded_and_does_not_pass():
    async with scanner_server(delay=1) as (port, _):
        settings = configured(port)
        settings.attachment_scan_timeout_seconds = 0.03
        async with asyncio.timeout(0.5):
            assert await file_scanner.scan_bytes(b'clean bytes', settings=settings) == 'ERROR'


async def test_unconfigured_scanner_never_opens_connection(monkeypatch):
    monkeypatch.setattr(file_scanner.asyncio, 'open_connection',
                        lambda *_: pytest.fail('unconfigured scanner opened a socket'))
    settings = Settings(_env_file=None, clamd_host='')
    assert await file_scanner.scan_bytes(b'clean bytes', settings=settings) == 'PENDING'
    report = await verify_scanner(settings=settings, include_test_signature=True)
    assert report['failures'] == 1
    assert report['checks'][1]['status'] == 'UNVERIFIED'


async def test_refused_connection_fails_closed():
    server = await asyncio.start_server(lambda *_: None, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    assert await file_scanner.scan_bytes(b'clean bytes', settings=configured(port)) == 'ERROR'


@pytest.mark.parametrize('include_signature', [False, True])
async def test_probe_requires_detection_and_uses_only_synthetic_memory(include_signature):
    def response(content):
        return b'stream: Eicar-Signature FOUND\0' if b'EICAR-' in content else b'stream: OK\0'
    async with scanner_server(response) as (port, requests):
        report = await verify_scanner(settings=configured(port), include_test_signature=include_signature)
    assert report['failures'] == 0 and report['production_acceptance'] is False
    assert report['checks'][1]['status'] == ('PASS' if include_signature else 'UNVERIFIED')
    assert len(requests) == (2 if include_signature else 1)
    if include_signature:
        assert len(requests[1]['content']) == 68
    assert 'EICAR-' not in json.dumps(report)


async def test_probe_does_not_confuse_always_clean_peer_with_working_antivirus():
    async with scanner_server() as (port, _):
        report = await verify_scanner(settings=configured(port), include_test_signature=True)
    assert report['failures'] == 1
    assert report['checks'][1]['code'] == 'test_signature_not_detected'


@pytest.mark.parametrize('values', [dict(clamd_port=0), dict(clamd_port=65536),
    dict(attachment_scan_timeout_seconds=0), dict(attachment_scan_timeout_seconds=61)])
def test_invalid_scanner_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
