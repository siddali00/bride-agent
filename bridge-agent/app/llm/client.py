import json
import logging
import time
from typing import Any, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/workflex/bridge-agent",
                "X-Title": "WorkFlex Bridge Agent",
            },
        )
    return _client


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    s = s[3:]
    if s.lower().startswith("json"):
        s = s[4:]
    s = s.lstrip("\r\n").lstrip()
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


async def json_call(
    system: str,
    user: str,
    schema: type[T],
    *,
    temperature: float = 0.0,
    max_tokens: int = 600,
) -> T:
    """Call the LLM in JSON mode and parse into `schema`.

    Raises `ValueError` on persistent parse failure. The pipeline catches
    this per-message so a single bad response never kills the batch.
    """
    start = time.perf_counter()
    resp = await get_client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    usage: dict[str, Any] = {}
    if resp.usage is not None:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
        }
    log.info("llm.call", extra={"latency_ms": latency_ms, **usage})

    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(_strip_code_fence(content))
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}; raw={content[:200]}") from e
    try:
        return schema.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"LLM JSON failed schema: {e}; raw={content[:200]}") from e
