from fastapi import FastAPI, Request, BackgroundTasks, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from typing import List
import uuid
import asyncio
import json
from datetime import datetime

from .models import (
    Conversation,
    Message,
    SendTextRequest,
    conversations_db,
    messages_db,
    create_or_get_conversation,
    Campaign,
    CampaignItem,
    CampaignCreate,
    campaigns_db,
    campaign_items_db,
    CampaignStatus,
    CampaignItemStatus,
)

from .meta_client import send_whatsapp_text, send_whatsapp_template

# =======================
# APP E CONFIG BÁSICA
# =======================

app = FastAPI(title="Painel WhatsApp Oficial")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # depois você pode restringir
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =======================
# PÁGINA PRINCIPAL (FRONT)
# =======================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# =======================
# API - CONVERSAS
# =======================

@app.get("/api/conversations", response_model=List[Conversation])
async def list_conversations():
    return list(conversations_db.values())


@app.get("/api/conversations/{conversation_id}/messages", response_model=List[Message])
async def get_conversation_messages(conversation_id: str):
    msgs = [
        m for m in messages_db.values()
        if m.conversation_id == conversation_id
    ]
    msgs.sort(key=lambda m: m.timestamp)
    return msgs


@app.post("/api/messages/text", response_model=Message)
async def send_text_message(payload: SendTextRequest):
    """
    Envia mensagem de texto pela API oficial da Meta e salva na "base" em memória.
    """
    # 1) Garante conversa
    conv = create_or_get_conversation(wa_id=payload.to)

    # 2) Envia na Meta
    meta_response_id = await send_whatsapp_text(
        to=payload.to,
        text=payload.message,
        phone_number_id=payload.phone_number_id
    )

    # 3) Cria mensagem local
    msg = Message.create_outgoing(
        conversation_id=conv.id,
        text=payload.message,
        meta_message_id=meta_response_id
    )
    messages_db[msg.id] = msg

    # Atualiza conversa
    conv.last_message_text = payload.message
    conv.last_message_at = datetime.utcnow()
    conv.unread_count = 0

    return msg


# =======================
# WEBHOOK META
# =======================

VERIFY_TOKEN = "SEU_VERIFY_TOKEN_AQUI"  # troque pelo mesmo token configurado na Meta


@app.get("/webhook/meta")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    Verificação inicial do webhook pela Meta.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return HTMLResponse(content=hub_challenge, status_code=200)
    return HTMLResponse(content="Erro de verificação", status_code=403)


@app.post("/webhook/meta")
async def receive_webhook(request: Request):
    """
    Recebe mensagens e status enviados pela Meta.
    Aqui salvamos mensagens RECEBIDAS dos clientes.
    """
    body = await request.json()

    entry = body.get("entry", [])
    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                from_wa = msg.get("from")  # 5511...
                text = msg.get("text", {}).get("body", "")
                timestamp = int(msg.get("timestamp", "0"))

                conv = create_or_get_conversation(wa_id=from_wa)

                new_msg = Message.create_incoming(
                    conversation_id=conv.id,
                    text=text,
                    wa_id=from_wa,
                    timestamp=timestamp
                )
                messages_db[new_msg.id] = new_msg

                conv.last_message_text = text
                conv.last_message_at = datetime.fromtimestamp(timestamp)
                conv.unread_count += 1
                conversations_db[conv.id] = conv

    return {"status": "ok"}


# =======================
# CAMPANHAS / DISPARO EM MASSA
# =======================

@app.post("/api/campaigns", response_model=Campaign)
async def create_campaign(payload: CampaignCreate, background_tasks: BackgroundTasks):
    """
    Cria uma campanha e dispara processo em background para enviar mensagens.
    """

    # Validação simples: ou template OU texto livre
    if not payload.template_name and not payload.message_text:
        raise ValueError("Informe template_name OU message_text.")

    if payload.template_name and payload.message_text:
        raise ValueError("Use apenas template_name OU message_text, não os dois.")

    campaign_id = str(uuid.uuid4())
    camp = Campaign(
        id=campaign_id,
        name=payload.name,
        phone_number_id=payload.phone_number_id,
        template_name=payload.template_name,
        template_language_code=payload.template_language_code,
        template_body_params=payload.template_body_params,
        message_text=payload.message_text,
        total=len(payload.to_numbers),
        sent=0,
        failed=0,
        status=CampaignStatus.pending
    )
    campaigns_db[camp.id] = camp

    for num in payload.to_numbers:
        item = CampaignItem(
            id=str(uuid.uuid4()),
            campaign_id=camp.id,
            to=num.strip(),
            status=CampaignItemStatus.pending
        )
        campaign_items_db[item.id] = item

    # dispara em background
    background_tasks.add_task(run_campaign, camp.id)

    return camp


@app.get("/api/campaigns", response_model=List[Campaign])
async def list_campaigns():
    return list(campaigns_db.values())


@app.get("/api/campaigns/{campaign_id}/items", response_model=List[CampaignItem])
async def list_campaign_items(campaign_id: str):
    return [
        it for it in campaign_items_db.values()
        if it.campaign_id == campaign_id
    ]


async def run_campaign(campaign_id: str):
    """
    Função que realmente envia as mensagens de uma campanha,
    chamada em background.
    """
    camp = campaigns_db.get(campaign_id)
    if not camp:
        return

    camp.status = CampaignStatus.running
    campaigns_db[campaign_id] = camp

    items = [it for it in campaign_items_db.values() if it.campaign_id == campaign_id]

    # Ajuste esse delay conforme sua estratégia / limite de envio
    DELAY_SECONDS = 0.2

    for item in items:
        try:
            if camp.template_name:
                # Envio via TEMPLATE oficial
                meta_msg_id = await send_whatsapp_template(
                    to=item.to,
                    phone_number_id=camp.phone_number_id,
                    template_name=camp.template_name,
                    language_code=camp.template_language_code or "pt_BR",
                    body_params=camp.template_body_params,
                )
            else:
                # Texto livre (somente se contato estiver dentro da janela de 24h)
                meta_msg_id = await send_whatsapp_text(
                    to=item.to,
                    text=camp.message_text,
                    phone_number_id=camp.phone_number_id
                )

            item.status = CampaignItemStatus.sent
            item.error_message = None
            camp.sent += 1

        except Exception as e:
            item.status = CampaignItemStatus.failed
            item.error_message = str(e)
            camp.failed += 1

        campaign_items_db[item.id] = item
        campaigns_db[campaign_id] = camp

        await asyncio.sleep(DELAY_SECONDS)

    camp.status = CampaignStatus.finished
    campaigns_db[campaign_id] = camp
