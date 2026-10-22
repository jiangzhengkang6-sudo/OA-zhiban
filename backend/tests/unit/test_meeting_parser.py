import pytest

from app.services.meeting_parser import MeetingParseError, MeetingParser


def test_rejects_blank_content_without_segments():
    with pytest.raises(MeetingParseError, match="内容不能为空"):
        MeetingParser().parse("  \n\t")


def test_rejects_content_over_configured_limit():
    parser = MeetingParser(max_chars=8)

    with pytest.raises(MeetingParseError, match="长度"):
        parser.parse("123456789")


def test_segments_mixed_language_text_with_stable_offsets_and_reconstruction():
    content = "项目进展已同步。The release is Friday!\n李雷：确认灰度范围？韩梅梅：确认。"

    segments = MeetingParser(max_chars=200).parse(content)

    assert [segment.ordinal for segment in segments] == [1, 2, 3, 4]
    assert "".join(segment.text for segment in segments) == content
    assert [(segment.start_offset, segment.end_offset) for segment in segments] == [
        (0, 8),
        (8, 31),
        (31, 41),
        (41, len(content)),
    ]
    assert all(segment.locator == f"chars:{segment.start_offset}-{segment.end_offset}" for segment in segments)


def test_splits_unpunctuated_long_text_without_losing_source_ranges():
    content = "甲" * 7 + "乙" * 7 + "丙" * 2

    segments = MeetingParser(max_chars=100, max_segment_chars=7).parse(content)

    assert [segment.text for segment in segments] == ["甲" * 7, "乙" * 7, "丙" * 2]
    assert all(content[s.start_offset:s.end_offset] == s.text for s in segments)


def test_segment_summary_does_not_include_full_sensitive_source():
    content = "员工身份证号 110101199001011234 已由人事确认。"

    segments = MeetingParser().parse(content)

    assert segments[0].text_hash
    assert content not in segments[0].summary
    assert "110101199001011234" not in segments[0].summary


def test_newline_runs_respect_segment_limit():
    content = "甲。" + "\n" * 15 + "结束。"
    segments = MeetingParser(max_segment_chars=4).parse(content)
    assert all(len(segment.text) <= 4 for segment in segments)
    assert "".join(segment.text for segment in segments) == content


def test_explicit_zero_segment_limit_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        MeetingParser(max_segment_chars=0)
