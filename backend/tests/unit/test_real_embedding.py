"""Offline checks for the live embedding transport and configuration aliases."""
import json

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.llm.base import LLMFactory


@pytest.fixture
def configure(monkeypatch):
    for name, value in {
        "EMBEDDING_PROVIDER": "ark", "EMBEDDING_DIM": "3",
        "EMBEDDING_API_KEY": "embedding-test-secret",
        "EMBEDDING_BASE_URL": "https://example.test/api/v3/embeddings/multimodal",
        "ARK_EMBEDDING_MODEL": "doubao-embedding-vision-251215",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
            **{**kwargs, "transport": httpx.MockTransport(handler)}))

    yield install
    get_settings.cache_clear()


def test_user_config_aliases_and_separate_embedding_credentials():
    config = Settings(_env_file=None, DEEPSEEK_MODEL="chosen-primary",
        DOUBAO_API_KEY="fallback-secret", DOUBAO_MODEL_NAME="chosen-fallback",
        DOUBAO_BASE_URL="https://fallback.test", EMBEDDING_MODEL="chosen-embedding",
        embedding_api_key="separate-embedding-secret")
    assert config.deepseek_chat_model == "chosen-primary"
    assert config.ark_api_key == "fallback-secret"
    assert config.ark_chat_model == "chosen-fallback"
    assert config.ark_base_url == "https://fallback.test"
    assert config.ark_embedding_model == "chosen-embedding"
    assert config.embedding_api_key != config.ark_api_key


@pytest.mark.asyncio
async def test_multimodal_embeds_each_text_independently_in_order(configure):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/api/v3/embeddings/multimodal"
        assert request.headers["authorization"] == "Bearer embedding-test-secret"
        assert body["dimensions"] == 3
        assert "office knowledge" in body["instructions"]
        assert body["input"] == [{"type": "text", "text": str(len(calls))}]
        return httpx.Response(200, json={"data": {"embedding": [len(calls), 0.0, 1.0]}})

    configure(handler)
    embedder = LLMFactory.get_embedding()
    assert await embedder.embed(["1", "2"]) == [[1, 0.0, 1.0], [2, 0.0, 1.0]]
    assert len(calls) == 2
    assert await embedder.embed([]) == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_standard_endpoint_reorders_batch_and_uses_ark_credentials(configure, monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/api/v3")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "text-embedding-model")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-secret")
    get_settings.cache_clear()

    def handler(request):
        assert request.url.path == "/api/v3/embeddings"
        assert request.headers["authorization"] == "Bearer ark-test-secret"
        assert json.loads(request.content)["input"] == ["1", "2"]
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [2, 0, 1]}, {"index": 0, "embedding": [1, 0, 1]}]})

    configure(handler)
    assert await LLMFactory.get_embedding().embed(["1", "2"]) == [[1, 0, 1], [2, 0, 1]]


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", [[1, 2], [0, 0, 0], [True, 1, 2], ["1", 1, 2], [None, 1, 2]])
async def test_invalid_vectors_are_rejected(configure, vector):
    configure(lambda request: httpx.Response(200, json={"data": {"embedding": vector}}))
    with pytest.raises(RuntimeError, match="invalid"):
        await LLMFactory.get_embedding().embed(["test"])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 429, 503, "timeout", "json"])
async def test_failures_are_not_mocked_retried_or_exposed(configure, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("embedding-test-secret private text", request=request)
        if failure == "json":
            return httpx.Response(200, text="private text embedding-test-secret")
        return httpx.Response(failure, text="private text embedding-test-secret")

    configure(handler)
    with pytest.raises(RuntimeError) as caught:
        await LLMFactory.get_embedding().embed(["test"])
    assert len(calls) == 1
    assert "embedding-test-secret" not in str(caught.value)
    assert "private text" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [[], [{"index": 1, "embedding": [1, 0, 0]}],
    [{"index": 0, "embedding": [1, 0, 0]}, {"index": 0, "embedding": [1, 0, 0]}]])
async def test_standard_batch_rejects_missing_or_duplicate_indices(configure, monkeypatch, items):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/api/v3/embeddings")
    get_settings.cache_clear()
    configure(lambda request: httpx.Response(200, json={"data": items}))
    with pytest.raises(RuntimeError, match="validation"):
        await LLMFactory.get_embedding().embed(["first", "second"])
