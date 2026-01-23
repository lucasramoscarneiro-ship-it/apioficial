import os
import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")

async def send_evolution_text(instance_name: str, to: str, text: str) -> dict:
    if not EVOLUTION_API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY não configurado")

    url = f"{EVOLUTION_BASE_URL}/api/v1/instances/{instance_name}/sendText"

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
            raise RuntimeError(
                f"Rota não encontrada no Evolution: {url}"
            )

        if r.status_code in (401, 403):
            raise RuntimeError("API KEY inválida ou sem permissão")

        r.raise_for_status()
        return r.json()
