import asyncio
from app.core.embedding import get_embedding
async def embed_text(text:str)->list[float]: return await asyncio.to_thread(get_embedding,text)
async def embed_many(texts:list[str],concurrency:int=4)->list[list[float]]:
    semaphore=asyncio.Semaphore(concurrency)
    async def one(text):
        async with semaphore:return await embed_text(text)
    return await asyncio.gather(*(one(t) for t in texts))
