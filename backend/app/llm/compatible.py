"""Bounded OpenAI-compatible text transport and one optional provider failover."""
import asyncio
import json
from collections.abc import Callable
from typing import TypeVar

import httpx
from pydantic import BaseModel

from ..core.config import get_settings

TModel = TypeVar("TModel", bound=BaseModel)


class ProviderUnavailable(RuntimeError):
    """Only temporary transport/server failures qualify for failover."""


class TextOperations:
    last_usage: dict
    last_attempts: list[dict]

    def _invalid_output(self):
        if self.last_attempts:
            self.last_attempts[-1]["status"] = "invalid_output"
        raise RuntimeError("model output failed validation") from None

    async def chat(self, messages: list[dict], *, model: str | None = None) -> str:
        data = await self.complete(messages, model=model)
        content = data["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            self._invalid_output()
        return content

    async def structured(self, messages: list[dict], schema: type[TModel], *,
                         model: str | None = None, max_tokens: int | None = None,
                         timeout_seconds: float | None = None) -> TModel:
        system = "只返回一个 JSON 对象，严格遵循 schema：\n" + json.dumps(
            schema.model_json_schema(), ensure_ascii=False)
        options = {"timeout_seconds": timeout_seconds} if timeout_seconds is not None else {}
        data = await self.complete([{"role": "system", "content": system}, *messages],
            model=model, max_tokens=max_tokens if max_tokens is not None else 2048,
            response_format={"type": "json_object"}, **options)
        content = data["choices"][0]["message"].get("content")
        try:
            return schema.model_validate(json.loads(content))
        except (ValueError, TypeError):
            self._invalid_output()


class CompatibleLLM(TextOperations):
    """One HTTP request, with no SDK retries and no provider response in errors."""

    def __init__(self, provider: str) -> None:
        settings = get_settings()
        if provider not in {"deepseek", "ark"}:
            raise ValueError("unsupported text provider")
        self.provider = provider
        self._base_url = getattr(settings, f"{provider}_base_url").rstrip("/")
        self._api_key = getattr(settings, f"{provider}_api_key").strip()
        self._model = getattr(settings, f"{provider}_chat_model").strip()
        self._timeout = settings.llm_timeout_seconds
        self._thinking_type = settings.ark_thinking_type
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self.last_usage = {}
        self.last_attempts = []

    async def complete(self, messages: list[dict], *, model: str | None = None,
                       max_tokens: int = 2048, tools: list[dict] | None = None,
                       response_format: dict | None = None,
                       timeout_seconds: float | None = None,
                       before_request: Callable[[], None] | None = None) -> dict:
        self.last_usage, self.last_attempts = {}, []
        try:
            if not 1 <= max_tokens <= 8192:
                raise ValueError("max_tokens outside supported budget")
            timeout = self._timeout if timeout_seconds is None else timeout_seconds
            if not 0 < timeout <= 60:
                raise ValueError("timeout outside supported budget")
            if not self._api_key or not (model or self._model):
                raise RuntimeError(f"{self.provider} model configuration is incomplete") from None
            body = {"model": model or self._model, "messages": messages, "max_tokens": max_tokens}
            if self.provider == "deepseek":
                # Non-thinking mode avoids reasoning history requirements during tool failover.
                body["thinking"] = {"type": "disabled"}
            elif self._thinking_type != "default":
                body["thinking"] = {"type": self._thinking_type}
            if tools:
                body["tools"] = tools
            if response_format:
                body["response_format"] = response_format
            if before_request:
                before_request()
            attempt = {"provider": self.provider, "model": body["model"], "status": "pending", "usage": {}}
            self.last_attempts.append(attempt)
            if self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self._timeout)
            try:
                async with asyncio.timeout(timeout):
                    response = await self._client.post(f"{self._base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"}, json=body, timeout=timeout)
            except (httpx.RequestError, TimeoutError):
                attempt["status"] = "unavailable"
                raise ProviderUnavailable(f"{self.provider} model temporarily unavailable") from None
            if response.status_code in {408, 429} or 500 <= response.status_code <= 599:
                attempt["status"] = "unavailable"
                raise ProviderUnavailable(f"{self.provider} model temporarily unavailable") from None
            if not 200 <= response.status_code < 300:
                attempt["status"] = "rejected"
                raise RuntimeError(f"{self.provider} model request rejected ({response.status_code})") from None
            try:
                data = response.json()
                raw_usage = data.get("usage")
                if isinstance(raw_usage, dict):
                    self.last_usage = {key: value for key, value in raw_usage.items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                        and isinstance(value, int) and not isinstance(value, bool) and value >= 0}
                attempt["usage"] = self.last_usage.copy()
                choice = data["choices"][0]
                item = choice["message"]
                if choice.get("finish_reason") not in {None, "stop", "tool_calls"}:
                    self._invalid_output()
                content = item.get("content")
                if content is not None and (not isinstance(content, str) or len(content) > max_tokens * 16):
                    self._invalid_output()
                if not isinstance(item.get("tool_calls", []), list):
                    self._invalid_output()
                if len(json.dumps(item, ensure_ascii=False)) > max_tokens * 16 + 1024:
                    self._invalid_output()
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                self._invalid_output()
            attempt["status"] = "success"
            return data
        finally:
            await self._client.aclose()


def build_client(provider: str) -> CompatibleLLM:
    return CompatibleLLM(provider)


class FailoverLLM(TextOperations):
    """A logical generation makes at most one primary and one fallback request."""

    def __init__(self, primary: str, fallback: str = "none") -> None:
        self.primary, self.fallback = primary, fallback
        self.last_usage, self.last_attempts = {}, []

    async def complete(self, messages: list[dict], **kwargs) -> dict:
        self.last_usage, self.last_attempts = {}, []
        providers = [self.primary]
        if self.fallback not in {"none", self.primary}:
            providers.append(self.fallback)
        for index, provider in enumerate(providers):
            client = build_client(provider)
            options = dict(kwargs)
            if index:
                # Model names and endpoint IDs are scoped to their own provider.
                options.pop("model", None)
            try:
                return await client.complete(messages, **options)
            except ProviderUnavailable:
                if index == len(providers) - 1:
                    raise ProviderUnavailable("configured text models are unavailable") from None
            finally:
                self.last_usage = client.last_usage.copy()
                self.last_attempts.extend(client.last_attempts)


def collect_usage(client) -> dict:
    usage = dict(getattr(client, "last_usage", {}) or {})
    attempts = getattr(client, "last_attempts", None)
    if attempts:
        usage["attempts"] = attempts
    return usage
