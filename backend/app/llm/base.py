"""
OA 智能体管理系统 - 模型调用抽象层。

定义 LLMClient / EmbeddingClient 抽象接口与工厂，屏蔽 Mock、DeepSeek 与 ARK 实现。
文本提供方与向量提供方分别配置，避免文本切换破坏已有知识库索引。
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..core.config import get_settings

TModel = TypeVar("TModel", bound=BaseModel)


class LLMClient(Protocol):
    """统一模型调用抽象：文本对话 + JSON 结构化输出。"""

    async def chat(self, messages: list[dict], *, model: str | None = None) -> str:
        """普通文本对话。

        Args:
            messages: OpenAI 风格消息列表。
            model: 可选模型名覆盖。

        Returns:
            str: 模型返回文本。
        """
        ...

    async def structured(
        self, messages: list[dict], schema: type[TModel], *, model: str | None = None,
        max_tokens: int | None = None, timeout_seconds: float | None = None
    ) -> TModel:
        """返回符合 schema 的结构化输出。

        Args:
            messages: 消息列表。
            schema: 目标 Pydantic 模型。
            model: 可选模型名覆盖。

        Returns:
            TModel: 校验后的结构化对象。
        """
        ...


class EmbeddingClient(Protocol):
    """向量化抽象接口。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本批量向量化。

        Args:
            texts: 待向量化文本。

        Returns:
            list[list[float]]: 与输入顺序对应的向量列表。
        """
        ...


class LLMFactory:
    """模型客户端工厂：按 LLM_PROVIDER 返回对应实现。"""

    @staticmethod
    def get_llm() -> LLMClient:
        """获取 LLM 客户端实例。

        Returns:
            LLMClient: Mock 或带主备切换的文本客户端。
        """
        settings = get_settings()
        if settings.llm_provider != "mock":
            from .compatible import FailoverLLM

            return FailoverLLM(settings.llm_provider, settings.llm_fallback_provider)
        from .mock_llm import MockLLM

        return MockLLM()

    @staticmethod
    def get_embedding() -> EmbeddingClient:
        """获取向量化客户端实例。

        Returns:
            EmbeddingClient: mock 或 ark 实现。
        """
        settings = get_settings()
        if settings.embedding_provider == "ark":
            from .embedding import ArkEmbedding

            return ArkEmbedding()
        from .embedding import MockEmbedding

        return MockEmbedding()
