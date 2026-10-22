"""Doubao text completions through the Volcengine Ark API."""
from .compatible import CompatibleLLM


class ArkLLM(CompatibleLLM):
    def __init__(self) -> None:
        super().__init__("ark")
