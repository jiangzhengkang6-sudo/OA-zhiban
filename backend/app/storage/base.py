"""Object storage contract."""

from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    def put(self, content: bytes, reference: str) -> str: ...
    def get(self, reference: str) -> bytes: ...
    def path(self, reference: str) -> Path: ...
