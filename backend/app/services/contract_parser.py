"""Bounded text extraction with exact source offsets; no instruction execution."""
import re
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 100000
MAX_PAGES = 100


def parse_text(text: str, pages: list[str] | None = None) -> dict:
    if not text.strip() or len(text) > MAX_CHARS:
        raise ValueError('合同正文为空或超过100000字符')
    paragraphs, offset = [], 0
    for page, content in enumerate(pages or [text], 1):
        for match in re.finditer(r'[^\r\n]+', content):
            if match.group().strip():
                paragraphs.append(dict(page=page, paragraph=len(paragraphs) + 1,
                    start=offset + match.start(), end=offset + match.end(), quote=match.group()))
        offset += len(content) + 1
    return dict(text=text, sha256=sha256(text.encode()).hexdigest(), paragraphs=paragraphs, pages=len(pages or [text]))


def parse_upload(filename: str, content_type: str, data: bytes) -> dict:
    if not data or len(data) > MAX_BYTES:
        raise ValueError('文件为空或超过5MiB')
    suffix = Path(filename).suffix.lower()
    if suffix == '.txt' and content_type in {'text/plain', 'application/octet-stream'}:
        return parse_text(data.decode('utf-8-sig'))
    if suffix != '.pdf' or content_type != 'application/pdf' or not data.startswith(b'%PDF-'):
        raise ValueError('仅接受UTF-8 TXT和文字PDF，文件类型不匹配')
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
            raise ValueError('加密PDF或页数超过100页')
        pages = []
        for page in reader.pages:
            content = page.extract_text() or ''
            if not content.strip():
                raise ValueError('扫描件或空白页需要人工处理')
            pages.append(content)
            if sum(map(len, pages)) + len(pages) > MAX_CHARS:
                raise ValueError('合同正文超过字符上限')
        return parse_text('\n'.join(pages), pages)
    except Exception as exc:
        raise ValueError('PDF无法解析、加密、含扫描页或超限') from exc


def validate_evidence(parsed: dict, evidence: dict, *, missing=False):
    start, end = evidence['start'], evidence['end']
    if not 0 <= start < end <= len(parsed['text']):
        raise ValueError('证据偏移越界')
    if missing:
        if start != 0 or end != len(parsed['text']) or evidence['quote']:
            raise ValueError('缺失条款须引用完整审查范围')
        return
    if not any(all(evidence.get(k) == p[k] for k in ('start', 'end', 'page', 'paragraph', 'quote')) for p in parsed['paragraphs']):
        raise ValueError('证据不匹配原文段落')

