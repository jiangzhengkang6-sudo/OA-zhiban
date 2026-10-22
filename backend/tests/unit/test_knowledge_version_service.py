from datetime import datetime, timedelta, timezone

import pytest

from app.services.knowledge_version_service import (
    build_version_metadata,
    next_version_number,
    validate_publish_window,
)


def test_next_version_number_increments_history_without_overwriting():
    assert next_version_number([]) == 1
    assert next_version_number([1, 3, 2]) == 4


def test_publish_window_rejects_expired_or_reversed_ranges():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="expire"):
        validate_publish_window(now, now - timedelta(minutes=1))
    with pytest.raises(ValueError, match="expired"):
        validate_publish_window(now - timedelta(days=2), now - timedelta(days=1), now=now)


def test_build_version_metadata_starts_as_ready_draft():
    metadata = build_version_metadata(
        content_hash="a" * 64,
        filename="guide.md",
        size_bytes=10,
        content_type="text/markdown",
    )
    assert metadata["status"] == "draft"
    assert metadata["parse_status"] == "READY"
    assert metadata["format"] == "md"
