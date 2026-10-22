"""
OA 智能体管理系统 - 向量化抽象与实现。

MockEmbedding 用文本哈希衍生确定性向量（离线可复现），ArkEmbedding 走火山方舟真实
embedding 接口。切换由 LLMFactory.get_embedding() 依据 EMBEDDING_PROVIDER 决定。
"""

import hashlib
import asyncio
import math

import httpx

from ..core.config import get_settings
from .base import EmbeddingClient


class MockEmbedding:
    """确定性 Mock 向量化实现（离线可复现）。"""

    def __init__(self) -> None:
        """初始化维度配置。"""
        self._dim = get_settings().embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """基于文本哈希生成确定性向量。

        Args:
            texts: 待向量化文本。

        Returns:
            list[list[float]]: 与输入顺序对应的向量。
        """
        return [self._hash_vector(t) for t in texts]

    def _hash_vector(self, text: str) -> list[float]:
        """基于字符 n-gram 特征哈希生成确定性向量（共享 n-gram 的文本相似度高）。

        Args:
            text: 待向量化文本。

        Returns:
            list[float]: 维度为 embedding_dim 的归一化向量。
        """
        vec = [0.0] * self._dim

        def bump(token: str, weight: float) -> None:
            """将 token 哈希到一个桶并累加权重。

            Args:
                token: 特征 token。
                weight: 累加权重。
            """
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            vec[idx] += weight

        # 字符 bigram（表达局部顺序），赋予较高权重
        for i in range(len(text) - 1):
            bump(text[i : i + 2], 1.0)
        # 单字符（表达词面重叠），赋予较低权重
        for ch in text:
            if not ch.isspace():
                bump(ch, 0.3)

        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


class ArkEmbedding:
    """ARK text and multimodal embeddings with independent credentials."""

    def __init__(self) -> None:
        """初始化端配置。"""
        settings = get_settings()
        base = (settings.embedding_base_url or settings.ark_base_url).rstrip("/")
        self._multimodal = base.endswith("/embeddings/multimodal") or (
            not base.endswith("/embeddings")
            and settings.ark_embedding_model.startswith("doubao-embedding-vision")
        )
        if base.endswith(("/embeddings", "/embeddings/multimodal")):
            self._url = base
        else:
            self._url = base + ("/embeddings/multimodal" if self._multimodal else "/embeddings")
        self._api_key = (settings.embedding_api_key or settings.ark_api_key).strip()
        self._model = settings.ark_embedding_model
        self._dim = settings.embedding_dim
        self._timeout = settings.embedding_timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 ARK embedding 接口批量向量化。

        Args:
            texts: 待向量化文本。

        Returns:
            list[list[float]]: 向量列表。

        Raises:
            RuntimeError: 调用失败时。
        """
        if not texts:
            return []
        if not self._api_key or not self._model.strip():
            raise RuntimeError("ark embedding configuration is incomplete") from None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if self._multimodal:
                vectors = []
                # Multiple items in one multimodal input form ONE fused vector.
                for text in texts:
                    body = {"model": self._model, "encoding_format": "float",
                        "input": [{"type": "text", "text": text}], "dimensions": self._dim}
                    if self._model.startswith("doubao-embedding-vision-251215"):
                        body["instructions"] = (
                            "Instruction:Represent the text for semantic similarity "
                            "and office knowledge retrieval.\nQuery:"
                        )
                    data = await self._request(client, body)
                    try:
                        vectors.append(self._validate_vector(data["data"]["embedding"]))
                    except (KeyError, TypeError):
                        raise RuntimeError("ark embedding output failed validation") from None
                return vectors
            data = await self._request(client, {"model": self._model, "input": texts})
            try:
                items = data["data"]
                if not isinstance(items, list) or len(items) != len(texts):
                    raise ValueError
                if sorted(item["index"] for item in items) != list(range(len(texts))):
                    raise ValueError
                return [self._validate_vector(item["embedding"])
                        for item in sorted(items, key=lambda item: item["index"])]
            except (KeyError, TypeError, ValueError):
                raise RuntimeError("ark embedding output failed validation") from None

    async def _request(self, client: httpx.AsyncClient, body: dict) -> dict:
        try:
            async with asyncio.timeout(self._timeout):
                response = await client.post(self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"}, json=body)
        except (httpx.RequestError, TimeoutError):
            raise RuntimeError("ark embedding temporarily unavailable") from None
        if not response.is_success:
            raise RuntimeError(f"ark embedding request rejected ({response.status_code})") from None
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError:
            raise RuntimeError("ark embedding output failed validation") from None

    def _validate_vector(self, vector) -> list[float]:
        if not isinstance(vector, list) or len(vector) != self._dim or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) for value in vector
        ) or not any(vector):
            raise RuntimeError("ark embedding output has invalid values or dimensions") from None
        return vector
