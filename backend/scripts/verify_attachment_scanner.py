"""Run from backend: python scripts/verify_attachment_scanner.py [--include-test-signature]."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.attachment_scanner import verify_scanner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-test-signature', action='store_true',
                        help='Also send the harmless EICAR antivirus test bytes in memory.')
    options = parser.parse_args()
    try:
        report = asyncio.run(verify_scanner(include_test_signature=options.include_test_signature))
    except Exception:
        print(json.dumps(dict(error='scanner_probe_failed', production_acceptance=False)))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
