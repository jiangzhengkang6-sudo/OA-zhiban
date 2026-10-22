"""Knowledge document chunking and file ingestion tests."""

import hashlib

from app.services.knowledge_service import (
    _CHUNK_SIZE,
    _split_chunks,
    preview_document,
)
from app.storage.local import LocalObjectStore


def test_split_chunks_supports_english_and_chinese_sentence_boundaries() -> None:
    chunks = _split_chunks("First sentence. Second sentence! 第三句？第四句。")

    assert chunks == ["First sentence.\nSecond sentence!\n第三句？\n第四句。"]


def test_split_chunks_keeps_markdown_headings_as_separate_units() -> None:
    chunks = _split_chunks("# Getting started\nUse the portal.\n\n## FAQ\nHow do I reset it?")

    assert chunks == [
        "# Getting started\nUse the portal.\n## FAQ\nHow do I reset it?"
    ]
    assert "portal.##" not in chunks[0]


def test_split_chunks_hard_splits_a_single_long_sentence() -> None:
    content = "x" * (_CHUNK_SIZE * 2 + 17)

    chunks = _split_chunks(content)

    assert [len(chunk) for chunk in chunks] == [_CHUNK_SIZE, _CHUNK_SIZE, 17]
    assert "".join(chunks) == content


def test_split_chunks_returns_one_empty_chunk_for_empty_content() -> None:
    assert _split_chunks("") == [""]


def test_preview_document_uses_parser_and_returns_file_hash_and_locations() -> None:
    preview = preview_document(b"# Guide\n\nWelcome.", "guide.md")

    assert preview["filename"] == "guide.md"
    assert preview["format"] == "md"
    assert preview["content_hash"] == hashlib.sha256(b"# Guide\n\nWelcome.").hexdigest()
    assert preview["blocks"][1]["section"] == "Guide"


def test_preview_document_can_persist_source_in_restricted_store(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    preview = preview_document(b"hello", "guide.md", store=store)

    assert preview["file_reference"].startswith("knowledge/")
    assert store.get(preview["file_reference"]) == b"hello"
