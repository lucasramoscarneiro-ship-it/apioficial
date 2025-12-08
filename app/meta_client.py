import httpx
import os
from dotenv import load_dotenv
from typing import List, Optional

load_dotenv()

META_BASE_URL = "https://graph.facebook.com/v21.0"
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")


async def send_whatsapp_text(to: str, text: str, phone_number_id: str) -> str:
    """
    Envia mensagem de TEXTO pela API oficial da Meta.
    Retorna o ID da mensagem gerado pela Meta.
    """
    if not META_ACCESS_TOKEN:
        raise RuntimeError("META_ACCESS_TOKEN não configurado no .env")

    url = f"{META_BASE_URL}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    msg_list = data.get("messages", [])
    if msg_list:
        return msg_list[0].get("id", "")

    return ""


async def send_whatsapp_template(
    to: str,
    phone_number_id: str,
    template_name: str,
    language_code: str = "pt_BR",
    body_params: Optional[List[str]] = None,
) -> str:
    """
    Envia mensagem de TEMPLATE oficial pela API da Meta.

    - template_name: nome exato do template aprovado (ex: 'promo_black_friday')
    - language_code: código do idioma do template (ex: 'pt_BR')
    - body_params: lista para preencher {{1}}, {{2}}, ... no corpo do template
    """
    if not META_ACCESS_TOKEN:
        raise RuntimeError("META_ACCESS_TOKEN não configurado no .env")

    url = f"{META_BASE_URL}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    components = []

    if body_params:
        body_component = {
            "type": "body",
            "parameters": [
                {"type": "text", "text": param} for param in body_params
            ],
        }
        components.append(body_component)

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            },
        },
    }

    if components:
        payload["template"]["components"] = components

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    msg_list = data.get("messages", [])
    if msg_list:
        return msg_list[0].get("id", "")

    return ""
