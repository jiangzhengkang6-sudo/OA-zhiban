"""B6 Task 6.1 bounded storage and document parsing contracts."""

import io

import pytest
from pypdf import PdfWriter

from app.services.document_parser import (
    MAX_DOCUMENT_BYTES,
    DocumentParseError,
    parse_bytes,
)
from app.storage.local import LocalObjectStore


def test_markdown_parser_preserves_heading_and_paragraph_locations():
    blocks = parse_bytes(b"# Title\n\nFirst paragraph.\n\n## FAQ\nAnswer.", "guide.md")
    assert blocks[0].text == "# Title"
    assert blocks[0].section == "Title"
    assert blocks[1].paragraph == 1
    assert blocks[2].section == "FAQ"


def test_html_parser_strips_tags_and_keeps_headings():
    blocks = parse_bytes(b"<html><body><h1>Guide</h1><p>Welcome <b>here</b>.</p></body></html>", "guide.html")
    assert [block.text for block in blocks] == ["Guide", "Welcome here."]
    assert blocks[1].section == "Guide"


def test_pdf_parser_emits_page_numbers():
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    blocks = parse_bytes(output.getvalue(), "blank.pdf")
    assert len(blocks) == 1
    assert blocks[0].page == 1


def test_empty_file_and_unsupported_type_are_rejected():
    with pytest.raises(ValueError, match="empty"):
        parse_bytes(b"", "empty.md")
    with pytest.raises(ValueError, match="unsupported"):
        parse_bytes(b"hello", "notes.txt")


def test_parser_exposes_stable_error_codes_for_boundaries():
    with pytest.raises(DocumentParseError) as empty: 
        parse_bytes(b"", "empty.md")
    assert empty.value.code == "empty_document"

    with pytest.raises(DocumentParseError) as unsupported:
        parse_bytes(b"hello", "notes.txt")
    assert unsupported.value.code == "unsupported_type"

    with pytest.raises(DocumentParseError) as oversized:
        parse_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1), "large.md")
    assert oversized.value.code == "file_too_large"


def test_parser_rejects_invalid_text_encoding_with_parse_error():
    with pytest.raises(DocumentParseError) as exc:
        parse_bytes(b"\xff\xfe", "broken.md")
    assert exc.value.code == "invalid_encoding"


def test_parser_rejects_malformed_pdf_with_parse_error():
    with pytest.raises(DocumentParseError) as exc:
        parse_bytes(b"%PDF-not-a-real-pdf", "broken.pdf")
    assert exc.value.code == "parse_error"


def test_local_store_rejects_path_escape_and_round_trips_bytes(tmp_path):
    store = LocalObjectStore(tmp_path)
    ref = store.put(b"hello", "tenant-a/source.md")
    assert store.get(ref) == b"hello"
    with pytest.raises(ValueError, match="path"):
        store.put(b"bad", "../outside")


def test_parser_blocks_have_uniform_location_shape():
    blocks = parse_bytes(b"# Intro\n\nBody", "guide.md")
    assert [set(block.__dict__) for block in blocks] == [
        {"text", "page", "section", "paragraph"},
        {"text", "page", "section", "paragraph"},
    ]
