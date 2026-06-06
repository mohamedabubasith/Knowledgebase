import httpx
from app.core.config import settings
class OllamaClient:
    def __init__(self): self.base_url=settings.ollama_url.rstrip("/")
    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=120) as client:
            r=await client.post(f"{self.base_url}/api/embeddings", json={"model":settings.embed_model,"prompt":text}); r.raise_for_status(); return r.json()["embedding"]
    async def generate(self, prompt: str, stream: bool=False):
        client=httpx.AsyncClient(timeout=300)
        r=await client.post(f"{self.base_url}/api/generate", json={"model":settings.llm_model,"prompt":prompt,"stream":stream})
        if not stream: r.raise_for_status(); await client.aclose(); return r.json()
        return r, client
    async def models(self):
        async with httpx.AsyncClient(timeout=30) as c: r=await c.get(f"{self.base_url}/api/tags"); r.raise_for_status(); return r.json().get("models",[])
    async def pull(self, model: str):
        async with httpx.AsyncClient(timeout=None) as c: r=await c.post(f"{self.base_url}/api/pull",json={"name":model,"stream":False}); r.raise_for_status(); return r.json()
ollama=OllamaClient()
