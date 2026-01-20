import os
import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://localhost:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")  # mesma do AUTHENTICATION_API_KEY

async def send_evolution_text(instance_name: str, to: str, text: str) -> dict:
    if not EVOLUTION_API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY não configurado no .env")

    url = f"{EVOLUTION_BASE_URL}/message/sendText/{instance_name}"

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "number": to,
        "text": text,  # ✅ formato certo da sua versão
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()
