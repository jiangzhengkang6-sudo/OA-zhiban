"""Filesystem object store constrained to one configured root."""

from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, reference: str) -> Path:
        if not reference or Path(reference).is_absolute():
            raise ValueError("invalid path reference")
        candidate = (self.root / reference).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("path escapes object store root")
        return candidate

    def put(self, content: bytes, reference: str) -> str:
        target = self.path(reference)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return reference.replace("\\", "/")

    def get(self, reference: str) -> bytes:
        return self.path(reference).read_bytes()
