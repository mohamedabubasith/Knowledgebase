from app.core.ollama import ollama


async def answer_question(prompt: str, sources: list[dict]) -> tuple[str, int]:
    context = "\n\n".join(f"[Source {i + 1}] {source['content']}" for i, source in enumerate(sources))
    request = f"""You are a multilingual knowledge-base assistant. Answer only from the supplied context. If the context does not contain the answer, say so. Cite sources as [Source N].

Context:
{context}

Question: {prompt}
Answer:"""
    result = await ollama.generate(request)
    return result.get("response", ""), result.get("eval_count", 0) + result.get("prompt_eval_count", 0)
