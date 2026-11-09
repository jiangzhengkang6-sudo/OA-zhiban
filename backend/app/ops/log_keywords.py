"""Bounded UTF-8 log scans. Persist only cursors, fingerprints and match times."""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .operations_monitor import atomic_json, read_json, result, stamp, timestamp

READ_LIMIT = 256 * 1024
BOUNDARY = 64


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load_receipt(path, tenant, now):
    if not path.exists():
        return None
    data = read_json(path)
    if (set(data) != {'version', 'tenant_id', 'configuration', 'sources'}
            or type(data['version']) is not int or data['version'] != 1 or data['tenant_id'] != tenant
            or not re.fullmatch('[a-f0-9]{64}', data['configuration'])
            or not isinstance(data['sources'], dict) or len(data['sources']) > 8):
        raise ValueError('Invalid receipt')
    for key, source in data['sources'].items():
        if (not re.fullmatch('[a-f0-9]{64}', key)
                or set(source) != {'offset', 'device', 'inode', 'boundary_length', 'boundary_hash', 'last_match_at'}):
            raise ValueError('Invalid source')
        for field in ('offset', 'device', 'inode', 'boundary_length'):
            if type(source[field]) is not int or source[field] < 0:
                raise ValueError('Invalid cursor')
        if (source['boundary_length'] != min(BOUNDARY, source['offset'])
                or not re.fullmatch('[a-f0-9]{64}', source['boundary_hash'])):
            raise ValueError('Invalid boundary')
        if source['last_match_at'] is not None and timestamp(source['last_match_at']) > now + timedelta(seconds=30):
            raise ValueError('Future match')
    return data


def read_source(path, previous, keywords, now):
    if not stat.S_ISREG(path.stat().st_mode):
        raise OSError('Regular file required')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError('Regular file required')
        offset = previous['offset'] if previous else 0
        last_match = previous['last_match_at'] if previous else None
        if previous:
            if (info.st_dev, info.st_ino) != (previous['device'], previous['inode']) or info.st_size < offset:
                offset = 0
            else:
                stream.seek(offset - previous['boundary_length'])
                if digest(stream.read(previous['boundary_length'])) != previous['boundary_hash']:
                    offset = 0
        # Reread a bounded prefix to match keywords split across reads or UTF-8 bytes.
        prefix_length = min(offset, max(len(word) for word in keywords) - 1)
        stream.seek(offset - prefix_length)
        prefix = stream.read(prefix_length)
        chunk = stream.read(READ_LIMIT)
        content = (prefix + chunk).lower()
        if any(content.find(word, max(0, prefix_length - len(word) + 1)) >= 0 for word in keywords):
            last_match = stamp(now)
        offset += len(chunk)
        boundary_length = min(BOUNDARY, offset)
        stream.seek(offset - boundary_length)
        boundary = stream.read(boundary_length)
        if len(boundary) != boundary_length:
            raise OSError('Log changed during scan')
        source = dict(offset=offset, device=info.st_dev, inode=info.st_ino,
                      boundary_length=boundary_length, boundary_hash=digest(boundary),
                      last_match_at=last_match)
        return source, os.fstat(stream.fileno()).st_size > offset


def scan(settings, now):
    """Caller serializes scans with the monitor lock; never return raw IO errors."""
    if not settings.ops_log_files:
        return result('log_keywords', 'WARN', 'log_disabled')
    receipt_path = Path(settings.ops_state_dir) / 'logs.json'
    try:
        previous = load_receipt(receipt_path, settings.auth_tenant_id, now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return result('log_keywords', 'FAIL', 'log_invalid')
    try:
        root = Path(settings.ops_state_dir).resolve()
        paths = list(dict.fromkeys(Path(value).resolve() for value in settings.ops_log_files))
        configuration = digest(json.dumps([list(map(str, paths)), settings.ops_log_keywords],
                                          ensure_ascii=True).encode())
        data = previous if previous and previous['configuration'] == configuration else dict(
            version=1, tenant_id=settings.auth_tenant_id, configuration=configuration, sources={})
        keywords = [word.encode('utf-8').lower() for word in settings.ops_log_keywords]
        unreadable = catching_up = False
        for path in paths:
            key = digest(os.path.normcase(str(path)).encode('utf-8'))
            try:
                if path == root or root in path.parents:
                    raise OSError('Private state is not a log source')
                source, pending = read_source(path, data['sources'].get(key), keywords, now)
                data['sources'][key] = source
                catching_up |= pending
            except (OSError, ValueError):
                unreadable = True
        atomic_json(receipt_path, data)
        matched = any(source['last_match_at'] is not None and
                      (now - timestamp(source['last_match_at'])).total_seconds() <= 300
                      for source in data['sources'].values())
        if unreadable:
            return result('log_keywords', 'FAIL', 'log_unreadable')
        if matched:
            return result('log_keywords', 'FAIL', 'log_matched')
        if catching_up:
            return result('log_keywords', 'WARN', 'log_catching_up')
        return result('log_keywords', 'PASS', 'log_clear')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RuntimeError):
        return result('log_keywords', 'FAIL', 'log_unreadable')
