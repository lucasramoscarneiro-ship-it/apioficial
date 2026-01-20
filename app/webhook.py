# app/webhook.py
from fastapi import APIRouter, Request

router = APIRouter(
    prefix="/webhook",
    tags=["Webhook"]
)

@router.post("")
async def evolution_webhook(request: Request):
    payload = await request.json()

    event = payload.get("event")
    instance = payload.get("instance")

    print("🔔 WEBHOOK RECEBIDO")
    print("Evento:", event)
    print("Instância:", instance)

    # EXEMPLO: capturar mensagem
    if event == "messages.upsert":
        messages = payload.get("data", {}).get("messages", [])
        for msg in messages:
            jid = msg.get("key", {}).get("remoteJid")
            text = msg.get("message", {}).get("conversation")
            print("📩 Mensagem:", jid, text)

    return {"status": "ok"}
