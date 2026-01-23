import os
import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")

async def send_evolution_text(instance_name: str, to: str, text: str) -> dict:
    if not EVOLUTION_API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY não configurado")

    # ✅ endpoint correto no seu Evolution (Railway)
    url = f"{EVOLUTION_BASE_URL}/message/sendText/{instance_name}"

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "number": to,
        "text": text,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)

        if r.status_code == 404:
            raise RuntimeError(f"404 do Evolution em {url}. Resposta: {r.text[:300]}")

        if r.status_code in (401, 403):
            raise RuntimeError(f"API KEY inválida/sem permissão. Resposta: {r.text[:300]}")

        r.raise_for_status()
        return r.json()
