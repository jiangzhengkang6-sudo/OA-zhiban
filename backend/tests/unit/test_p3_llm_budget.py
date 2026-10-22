import httpx
import pytest
from pydantic import BaseModel
from app.llm.ark_llm import ArkLLM


class Result(BaseModel):
    summary: str


@pytest.mark.asyncio
async def test_structured_sends_output_cap_and_preserves_actual_usage():
    observed = []
    def respond(request):
        import json
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"ok"}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}})
    model = ArkLLM()
    model._api_key, model._model = "offline-test-key", "offline-test-model"
    await model._client.aclose()
    model._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await model.structured([], Result, max_tokens=2048)
        assert result.summary == "ok"
        assert observed[0]["max_tokens"] == 2048
        assert model.last_usage == {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}
    finally:
        await model._client.aclose()
