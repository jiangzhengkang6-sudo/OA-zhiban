"""Synthetic scanner checks without files, database access or application startup."""
from datetime import datetime, timezone

from ..core.config import get_settings
from ..providers.file_scanner import scan_bytes


async def verify_scanner(*, settings=None, include_test_signature=False):
    settings = settings or get_settings()
    checks = []
    if not settings.clamd_host:
        checks.append(dict(check='clean_stream', status='FAIL', code='scanner_not_configured'))
    else:
        outcome = await scan_bytes(b'OA synthetic clean attachment scanner check.\n', settings=settings)
        checks.append(dict(check='clean_stream', status='PASS' if outcome == 'CLEAN' else 'FAIL',
                           code='clean_stream_accepted' if outcome == 'CLEAN' else 'clean_stream_not_accepted'))
    if include_test_signature and settings.clamd_host:
        # Standard harmless antivirus test signature; never written to disk.
        signature = b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$' + b'EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
        outcome = await scan_bytes(signature, settings=settings)
        checks.append(dict(check='test_signature', status='PASS' if outcome == 'INFECTED' else 'FAIL',
                           code='test_signature_detected' if outcome == 'INFECTED' else 'test_signature_not_detected'))
    else:
        checks.append(dict(check='test_signature', status='UNVERIFIED', code='test_signature_not_sent'))
    return dict(checked_at=datetime.now(timezone.utc).isoformat(), checks=checks,
                failures=sum(item['status'] == 'FAIL' for item in checks),
                production_acceptance=False,
                boundary='Synthetic INSTREAM only; no business files, disk writes or application startup.')
