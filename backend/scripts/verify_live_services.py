"""Run from backend: python scripts/verify_live_services.py [--include-standby]."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.live_services import verify_services


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-standby", action="store_true",
                        help="Also probe non-selected text providers with configured credentials.")
    options = parser.parse_args()
    try:
        report = asyncio.run(verify_services(include_standby=options.include_standby))
    except Exception:
        print(json.dumps({"error": "preflight_failed", "production_acceptance": False}))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
