from app.core.llm import generate_response


async def answer_question(prompt: str, sources: list[dict]) -> tuple[str, int]:
    context = "\n\n".join(f"[Source {i + 1}] {source['content']}" for i, source in enumerate(sources))
    result = await generate_response(prompt, context)
    return result["text"], result["tokens_used"]
