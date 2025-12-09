from fastapi import FastAPI, Request, BackgroundTasks, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

import asyncio
from datetime import datetime
import os

from .db import get_conn
from .meta_client import send_whatsapp_text, send_whatsapp_template
from .models import (
    SendTextRequest,
    CampaignCreate,
)

app = FastAPI(title="Painel WhatsApp Oficial (API Oficial Meta)")

# arquivos estáticos (CSS/JS) e templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "SEU_VERIFY_TOKEN_AQUI")


# =======================
# FRONTEND - PÁGINA ÚNICA COM ABAS
# =======================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Página única da plataforma, com abas:
    - Conversas
    - Campanhas
    """
    return templates.TemplateResponse("index.html", {"request": request})


# =======================
# CONVERSAS E MENSAGENS (CHAT)
# =======================

@app.get("/api/conversations")
async def list_conversations():
    """
    Lista conversas salvas no banco, ordenadas pela última mensagem.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, wa_id, name, last_message_text, last_message_at, unread_count, created_at
        FROM conversations
        ORDER BY last_message_at DESC NULLS LAST, created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    """
    Lista mensagens de uma conversa específica.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp, created_at
        FROM messages
        WHERE conversation_id = %s
        ORDER BY timestamp ASC
    """, (conversation_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.post("/api/messages/text")
async def send_text_message(payload: SendTextRequest):
    """
    Envia mensagem de texto pela API oficial da Meta
    e salva mensagem + conversa no banco (Supabase/Postgres).
    """
    # 1) Envia para a API da Meta
    meta_id = await send_whatsapp_text(
        to=payload.to,
        text=payload.message,
        phone_number_id=payload.phone_number_id
    )

    conn = get_conn()
    cur = conn.cursor()

    # 2) Garante que a conversa existe
    cur.execute("SELECT id FROM conversations WHERE wa_id = %s", (payload.to,))
    row = cur.fetchone()

    if row:
        conversation_id = row["id"]
    else:
        cur.execute("""
            INSERT INTO conversations (wa_id, name, last_message_text, last_message_at, unread_count)
            VALUES (%s, %s, %s, NOW(), 0)
            RETURNING id
        """, (payload.to, payload.to, payload.message))
        conversation_id = cur.fetchone()["id"]

    # 3) Insere a mensagem enviada
    cur.execute("""
        INSERT INTO messages (
            conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
        )
        VALUES (%s, 'outgoing', 'text', %s, %s, 'sent', %s, NOW())
    """, (conversation_id, payload.message, payload.to, meta_id))

    # 4) Atualiza dados da conversa
    cur.execute("""
        UPDATE conversations
        SET last_message_text = %s,
            last_message_at = NOW(),
            unread_count = 0
        WHERE id = %s
    """, (payload.message, conversation_id))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "sent",
        "conversation_id": conversation_id,
        "meta_message_id": meta_id,
    }


# =======================
# WEBHOOK META
# =======================

@app.get("/webhook/meta")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    Utilizado pela Meta para verificar o webhook.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return HTMLResponse(content=hub_challenge, status_code=200)
    return HTMLResponse(content="Erro de verificação", status_code=403)


@app.post("/webhook/meta")
async def receive_webhook(request: Request):
    """
    Recebe mensagens e status enviados pela Meta.
    Aqui salvamos mensagens RECEBIDAS dos clientes no banco.
    """
    body = await request.json()
    entries = body.get("entry", [])

    conn = get_conn()
    cur = conn.cursor()

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                from_wa = msg.get("from")  # telefone 5511...
                text = msg.get("text", {}).get("body", "")
                ts_str = msg.get("timestamp", "0")
                try:
                    ts = int(ts_str)
                except ValueError:
                    ts = int(datetime.utcnow().timestamp())

                # 1) Garante a conversa
                cur.execute("SELECT id FROM conversations WHERE wa_id = %s", (from_wa,))
                row = cur.fetchone()

                if row:
                    conversation_id = row["id"]
                else:
                    cur.execute("""
                        INSERT INTO conversations (wa_id, name, last_message_text, last_message_at, unread_count)
                        VALUES (%s, %s, %s, TO_TIMESTAMP(%s), 1)
                        RETURNING id
                    """, (from_wa, from_wa, text, ts))
                    conversation_id = cur.fetchone()["id"]

                # 2) Insere mensagem recebida
                cur.execute("""
                    INSERT INTO messages (
                        conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
                    )
                    VALUES (%s, 'incoming', 'text', %s, %s, 'received', NULL, TO_TIMESTAMP(%s))
                """, (conversation_id, text, from_wa, ts))

                # 3) Atualiza conversa
                cur.execute("""
                    UPDATE conversations
                    SET last_message_text = %s,
                        last_message_at = TO_TIMESTAMP(%s),
                        unread_count = unread_count + 1
                    WHERE id = %s
                """, (text, ts, conversation_id))

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ok"}


# =======================
# CAMPANHAS (DISPARO EM MASSA)
# =======================

@app.post("/api/campaigns")
async def create_campaign(payload: CampaignCreate, background_tasks: BackgroundTasks):
    """
    Cria uma campanha de disparo em massa (texto livre ou template)
    e dispara o envio em background.
    """

    # Valida: ou template OU texto
    if not payload.template_name and not payload.message_text:
        return {"error": "Informe template_name OU message_text."}

    if payload.template_name and payload.message_text:
        return {"error": "Use apenas template_name OU message_text, não os dois."}

    conn = get_conn()
    cur = conn.cursor()

    # Cria campanha
    cur.execute("""
        INSERT INTO campaigns (
            name,
            phone_number_id,
            template_name,
            template_language_code,
            template_body_params,
            message_text,
            total,
            sent,
            failed,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 'pending')
        RETURNING id
    """, (
        payload.name,
        payload.phone_number_id,
        payload.template_name,
        payload.template_language_code or "pt_BR",
        payload.template_body_params,
        payload.message_text,
        len(payload.to_numbers),
    ))
    row = cur.fetchone()
    campaign_id = row["id"]

    # Cria items
    for num in payload.to_numbers:
        num_clean = num.strip()
        if not num_clean:
            continue
        cur.execute("""
            INSERT INTO campaign_items (campaign_id, "to", status)
            VALUES (%s, %s, 'pending')
        """, (campaign_id, num_clean))

    conn.commit()
    cur.close()
    conn.close()

    # dispara em background
    background_tasks.add_task(run_campaign, campaign_id)

    return {"status": "created", "campaign_id": campaign_id}


@app.get("/api/campaigns")
async def list_campaigns():
    """
    Lista campanhas.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, phone_number_id, template_name, template_language_code,
               message_text, total, sent, failed, status, created_at
        FROM campaigns
        ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/api/campaigns/{campaign_id}/items")
async def list_campaign_items(campaign_id: str):
    """
    Lista itens (números) de uma campanha.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, campaign_id, "to", status, error_message, created_at
        FROM campaign_items
        WHERE campaign_id = %s
        ORDER BY created_at ASC
    """, (campaign_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


async def run_campaign(campaign_id: str):
    """
    Envia as mensagens de uma campanha em background.
    """
    conn = get_conn()
    cur = conn.cursor()

    # Busca campanha
    cur.execute("SELECT * FROM campaigns WHERE id = %s", (campaign_id,))
    camp = cur.fetchone()
    if not camp:
        cur.close()
        conn.close()
        return

    # Atualiza status para running
    cur.execute("""
        UPDATE campaigns
        SET status = 'running'
        WHERE id = %s
    """, (campaign_id,))
    conn.commit()

    template_name = camp["template_name"]
    template_language_code = camp["template_language_code"] or "pt_BR"
    template_body_params = camp["template_body_params"]
    message_text = camp["message_text"]
    phone_number_id = camp["phone_number_id"]

    # Busca itens pendentes
    cur.execute("""
        SELECT id, "to", status
        FROM campaign_items
        WHERE campaign_id = %s AND status = 'pending'
        ORDER BY created_at ASC
    """, (campaign_id,))
    items = cur.fetchall()

    DELAY_SECONDS = 0.2

    sent = camp["sent"]
    failed = camp["failed"]

    for item in items:
        item_id = item["id"]
        to_number = item["to"]

        try:
            if template_name:
                # Envio via TEMPLATE oficial
                await send_whatsapp_template(
                    to=to_number,
                    phone_number_id=phone_number_id,
                    template_name=template_name,
                    language_code=template_language_code,
                    body_params=template_body_params,
                )
            else:
                # Envio de TEXTO livre (apenas dentro da janela de 24h)
                await send_whatsapp_text(
                    to=to_number,
                    text=message_text,
                    phone_number_id=phone_number_id,
                )

            cur.execute("""
                UPDATE campaign_items
                SET status = 'sent', error_message = NULL
                WHERE id = %s
            """, (item_id,))
            sent += 1

        except Exception as e:
            cur.execute("""
                UPDATE campaign_items
                SET status = 'failed', error_message = %s
                WHERE id = %s
            """, (str(e), item_id))
            failed += 1

        cur.execute("""
            UPDATE campaigns
            SET sent = %s, failed = %s
            WHERE id = %s
        """, (sent, failed, campaign_id))

        conn.commit()
        await asyncio.sleep(DELAY_SECONDS)

    cur.execute("""
        UPDATE campaigns
        SET status = 'finished'
        WHERE id = %s
    """, (campaign_id,))
    conn.commit()

    cur.close()
    conn.close()
