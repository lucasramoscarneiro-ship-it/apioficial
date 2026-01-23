import os
import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")  # mesma do AUTHENTICATION_API_KEY

async def send_evolution_text(instance_name: str, to: str, text: str) -> dict:
    if not EVOLUTION_API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY não configurado")

    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

    payload_basic = {"number": to, "text": text}

    # lista de rotas prováveis (Railway pode estar diferente do localhost)
    candidates = [
        # formato A: instance na URL
        (f"{EVOLUTION_BASE_URL}/message/sendText/{instance_name}", payload_basic),
        (f"{EVOLUTION_BASE_URL}/messages/sendText/{instance_name}", payload_basic),
        (f"{EVOLUTION_BASE_URL}/api/message/sendText/{instance_name}", payload_basic),
        (f"{EVOLUTION_BASE_URL}/api/messages/sendText/{instance_name}", payload_basic),

        # formato B: instance no body
        (f"{EVOLUTION_BASE_URL}/message/sendText", {"instanceName": instance_name, **payload_basic}),
        (f"{EVOLUTION_BASE_URL}/messages/sendText", {"instanceName": instance_name, **payload_basic}),
        (f"{EVOLUTION_BASE_URL}/api/message/sendText", {"instanceName": instance_name, **payload_basic}),
        (f"{EVOLUTION_BASE_URL}/api/messages/sendText", {"instanceName": instance_name, **payload_basic}),
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        last_text = None
        for url, payload in candidates:
            r = await client.post(url, headers=headers, json=payload)
            last_text = r.text

            if r.status_code == 404:
                continue  # tenta a próxima rota

            if r.status_code in (401, 403):
                raise RuntimeError(f"Evolution respondeu {r.status_code}. API KEY incorreta ou sem permissão. URL: {url}")

            r.raise_for_status()
            return r.json()

    raise RuntimeError(f"Nenhuma rota de envio funcionou (todas 404). Última resposta: {last_text}")
