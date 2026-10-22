"""Deterministic Markdown, HTML and PDF parser with source locations."""

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from io import BytesIO

from pypdf import PdfReader

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
SUPPORTED_SUFFIXES = {".md", ".markdown", ".html", ".htm", ".pdf"}


class DocumentParseError(ValueError):
    """Stable, user-safe parser failure with a machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None


def parse_bytes(content: bytes, filename: str) -> list[ParsedBlock]:
    if not content:
        raise DocumentParseError("empty_document", "empty document")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentParseError("file_too_large", "document exceeds maximum size")
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return _decode_text(content, _parse_markdown)
    if suffix in {".html", ".htm"}:
        return _decode_text(content, _parse_html)
    if suffix == ".pdf":
        try:
            return _parse_pdf(content)
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError("parse_error", "unable to parse PDF") from exc
    raise DocumentParseError("unsupported_type", "unsupported document type")


def _decode_text(content: bytes, parser) -> list[ParsedBlock]:
    try:
        return parser(content.decode("utf-8-sig", errors="strict"))
    except UnicodeDecodeError as exc:
        raise DocumentParseError("invalid_encoding", "document must be UTF-8") from exc


def _parse_markdown(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    section = None
    paragraph = 0
    current: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines() + [""]:
        value = line.strip()
        if not value:
            if current:
                paragraph += 1
                blocks.append(ParsedBlock("\n".join(current), section=section, paragraph=paragraph))
                current = []
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", value)
        if heading:
            if current:
                paragraph += 1
                blocks.append(ParsedBlock("\n".join(current), section=section, paragraph=paragraph))
                current = []
            section = heading.group(2).strip()
            blocks.append(ParsedBlock(value, section=section))
        else:
            current.append(value)
    return blocks


class _HTMLTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks: list[tuple[str, bool]] = []
        self.current: list[str] = []
        self.heading = False
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading = True
        if tag in {"p", "div", "li", "br"} and self.current:
            self._flush()

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li"}:
            self._flush()
            self.heading = False

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.current.append(data.strip())

    def _flush(self):
        value = re.sub(r"\s+", " ", " ".join(self.current)).strip()
        value = re.sub(r"\s+([,.;:!?。！？])", r"\1", value)
        if value:
            self.blocks.append((value, self.heading))
        self.current = []

    def close(self):
        super().close()
        self._flush()


def _parse_html(text: str) -> list[ParsedBlock]:
    parser = _HTMLTextParser()
    parser.feed(text)
    parser.close()
    section = None
    paragraph = 0
    result = []
    for value, is_heading in parser.blocks:
        if is_heading:
            section = value
            result.append(ParsedBlock(value, section=section))
        else:
            paragraph += 1
            result.append(ParsedBlock(value, section=section, paragraph=paragraph))
    return result


def _parse_pdf(content: bytes) -> list[ParsedBlock]:
    reader = PdfReader(BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted PDF is unsupported")
    result = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        result.append(ParsedBlock(text, page=page_number, paragraph=1 if text else None))
    return result or [ParsedBlock("", page=1)]
