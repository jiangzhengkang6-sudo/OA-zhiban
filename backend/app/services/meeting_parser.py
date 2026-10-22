"""Validate and split pasted meeting text without leaking it to logs."""

import hashlib

from ..schemas.meeting import MeetingSegmentDTO


class MeetingParseError(ValueError):
    """Stable, user-facing meeting input validation error."""

    def __init__(self, message: str, *, code: str = "MEETING_INPUT_INVALID") -> None:
        super().__init__(message)
        self.code = code


class MeetingParser:
    """Pure parser that preserves exact source ranges and ordering."""

    DEFAULT_MAX_CHARS = 50_000
    _BOUNDARY_CHARS = frozenset("。！？!?；;")

    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS, max_segment_chars: int | None = None) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self.max_chars = max_chars
        self.max_segment_chars = min(max_chars, 2_000) if max_segment_chars is None else max_segment_chars
        if self.max_segment_chars < 1:
            raise ValueError("max_segment_chars must be positive")

    def parse(self, content: str) -> list[MeetingSegmentDTO]:
        if not isinstance(content, str) or not content.strip():
            raise MeetingParseError("会议内容不能为空")
        if len(content) > self.max_chars:
            raise MeetingParseError("会议内容超过长度上限，请分段提交", code="MEETING_CONTENT_TOO_LONG")

        segments: list[MeetingSegmentDTO] = []
        start = 0
        ordinal = 1
        while start < len(content):
            end = self._next_end(content, start)
            text = content[start:end]
            if text:
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                segments.append(
                    MeetingSegmentDTO(
                        segment_id=f"seg-{ordinal:04d}",
                        ordinal=ordinal,
                        start_offset=start,
                        end_offset=end,
                        text=text,
                        locator=f"chars:{start}-{end}",
                        text_hash=digest,
                        summary=f"segment {ordinal} ({len(text)} chars)",
                    )
                )
                ordinal += 1
            start = end
        return segments

    def _next_end(self, content: str, start: int) -> int:
        limit = min(len(content), start + self.max_segment_chars)
        boundary = None
        for index in range(start, limit):
            char = content[index]
            if char in self._BOUNDARY_CHARS or char == "\n":
                boundary = index + 1
                break
        if boundary is not None:
            while boundary < limit and content[boundary] == "\n":
                boundary += 1
            return boundary
        return limit

