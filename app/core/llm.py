import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)


def _base_url() -> str:
    url = settings.tabular_sql_base_url.strip()
    if not url:
        raise RuntimeError("TABULAR_SQL_BASE_URL is not configured — required for LLM responses")
    return url.rstrip("/")


async def generate_response(
    prompt: str,
    context: str,
    system: str | None = None,
    max_new_tokens: int = 512,
    temperature: float = 0.7,
) -> dict:
    messages = [
        {
            "role": "system",
            "content": system or "Answer only from the supplied context. Be concise. Cite sources as [Source N].",
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {prompt}",
        },
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.tabular_sql_api_key or 'local'}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.tabular_sql_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_new_tokens,
                "stream": False,
            },
        )
        resp.raise_for_status()

    data = resp.json()
    text = data["choices"][0]["message"].get("content", "").strip()
    tokens = data.get("usage", {}).get("total_tokens", 0)

    log.info("llm_response_ok", model=settings.tabular_sql_model, tokens=tokens)
    return {"text": text, "tokens_used": tokens, "model": settings.tabular_sql_model}
