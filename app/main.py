from fastapi import FastAPI, Request, BackgroundTasks, Query, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

import asyncio
from datetime import datetime
import os

from psycopg2.extras import RealDictCursor

from .db import get_conn
from .meta_client import send_whatsapp_text, send_whatsapp_template
from .models import SendTextRequest, CampaignCreate
from .politica import router as politica_router
from .termos import router as termos_router

from .auth.auth_router import router as auth_router
from .auth.dependencies import get_current_user


app = FastAPI(title="Painel WhatsApp Oficial (API Oficial Meta)")

app.include_router(auth_router)
app.include_router(politica_router)
app.include_router(termos_router)

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
    return templates.TemplateResponse("index.html", {"request": request})


# =======================
# HELPERS
# =======================

def _dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)

def _get_user_id(user):
    # get_current_user retorna dict
    return str(user["id"])


# =======================
# CONVERSAS E MENSAGENS (CHAT) - PROTEGIDO
# =======================

@app.get("/api/conversations")
async def list_conversations(user=Depends(get_current_user)):
    """
    Lista somente conversas do usuário logado.
    """
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        SELECT id, wa_id, name, last_message_text, last_message_at, unread_count, created_at
        FROM conversations
        WHERE user_id = %s
        ORDER BY last_message_at DESC NULLS LAST, created_at DESC
    """, (_get_user_id(user),))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, user=Depends(get_current_user)):
    """
    Lista mensagens de uma conversa específica, mas só se a conversa for do usuário.
    """
    conn = get_conn()
    cur = _dict_cursor(conn)

    # garante dono
    cur.execute("SELECT id FROM conversations WHERE id=%s AND user_id=%s", (conversation_id, _get_user_id(user)))
    owner = cur.fetchone()
    if not owner:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

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
async def send_text_message(payload: SendTextRequest, user=Depends(get_current_user)):
    """
    Envia mensagem e salva no banco.
    Só permite enviar em conversas do próprio usuário (pelo wa_id).
    """
    user_id = _get_user_id(user)

    conn = get_conn()
    cur = _dict_cursor(conn)

    # conversa precisa pertencer ao usuário
    cur.execute("SELECT id FROM conversations WHERE wa_id=%s AND user_id=%s", (payload.to, user_id))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Conversa não pertence ao usuário")

    conversation_id = row["id"]

    # 1) Envia para a API da Meta
    meta_id = await send_whatsapp_text(
        to=payload.to,
        text=payload.message,
        phone_number_id=payload.phone_number_id
    )

    # 2) Insere a mensagem enviada
    cur.execute("""
        INSERT INTO messages (
            conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
        )
        VALUES (%s, 'outgoing', 'text', %s, %s, 'sent', %s, NOW())
    """, (conversation_id, payload.message, payload.to, meta_id))

    # 3) Atualiza dados da conversa
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

    return {"status": "sent", "conversation_id": conversation_id, "meta_message_id": meta_id}


# =======================
# WEBHOOK META - NÃO PROTEGIDO (OBRIGATÓRIO)
# =======================

@app.get("/webhook/meta")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return HTMLResponse(content=hub_challenge, status_code=200)
    return HTMLResponse(content="Erro de verificação", status_code=403)


@app.post("/webhook/meta")
async def receive_webhook(request: Request):
    """
    Recebe mensagens e status enviados pela Meta.
    Salva mensagens RECEBIDAS no banco.
    Atribui a conversa ao usuário correto via metadata.phone_number_id.
    """
    body = await request.json()
    entries = body.get("entry", [])

    conn = get_conn()
    cur = _dict_cursor(conn)

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            metadata = value.get("metadata", {}) or {}
            phone_number_id = metadata.get("phone_number_id")

            # Descobrir o usuário dono desse phone_number_id
            user_id = None
            if phone_number_id:
                cur.execute("""
                    SELECT id FROM users
                    WHERE phone_number_id = %s AND is_active = true
                    LIMIT 1
                """, (str(phone_number_id),))
                u = cur.fetchone()
                if u:
                    user_id = str(u["id"])

            # Se não achar usuário, ainda salva (mas sem user_id) OU você pode ignorar.
            # Aqui vamos salvar user_id NULL se não achar.
            messages = value.get("messages", [])
            for msg in messages:
                from_wa = msg.get("from")  # telefone 5511...
                text = msg.get("text", {}).get("body", "")
                ts_str = msg.get("timestamp", "0")

                try:
                    ts = int(ts_str)
                except ValueError:
                    ts = int(datetime.utcnow().timestamp())

                # 1) Garante a conversa (sempre do mesmo user_id)
                if user_id:
                    cur.execute("""
                        SELECT id FROM conversations
                        WHERE wa_id = %s AND user_id = %s
                    """, (from_wa, user_id))
                else:
                    cur.execute("""
                        SELECT id FROM conversations
                        WHERE wa_id = %s AND user_id IS NULL
                    """, (from_wa,))
                row = cur.fetchone()

                if row:
                    conversation_id = row["id"]
                else:
                    cur.execute("""
                        INSERT INTO conversations (user_id, wa_id, name, last_message_text, last_message_at, unread_count)
                        VALUES (%s, %s, %s, %s, TO_TIMESTAMP(%s), 1)
                        RETURNING id
                    """, (user_id, from_wa, from_wa, text, ts))
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
# CAMPANHAS (DISPARO EM MASSA) - PROTEGIDO
# =======================

@app.post("/api/campaigns")
async def create_campaign(payload: CampaignCreate, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    """
    Cria campanha do usuário logado e dispara em background.
    """
    user_id = _get_user_id(user)

    if not payload.template_name and not payload.message_text:
        return {"error": "Informe template_name OU message_text."}

    if payload.template_name and payload.message_text:
        return {"error": "Use apenas template_name OU message_text, não os dois."}

    conn = get_conn()
    cur = _dict_cursor(conn)

    cur.execute("""
        INSERT INTO campaigns (
            user_id,
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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 'pending')
        RETURNING id
    """, (
        user_id,
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

    background_tasks.add_task(run_campaign, campaign_id)
    return {"status": "created", "campaign_id": campaign_id}


@app.get("/api/campaigns")
async def list_campaigns(user=Depends(get_current_user)):
    """
    Lista somente campanhas do usuário logado.
    """
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        SELECT id, name, phone_number_id, template_name, template_language_code,
               message_text, total, sent, failed, status, created_at
        FROM campaigns
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (_get_user_id(user),))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/api/campaigns/{campaign_id}/items")
async def list_campaign_items(campaign_id: str, user=Depends(get_current_user)):
    """
    Lista itens da campanha se ela for do usuário.
    """
    conn = get_conn()
    cur = _dict_cursor(conn)

    cur.execute("SELECT id FROM campaigns WHERE id=%s AND user_id=%s", (campaign_id, _get_user_id(user)))
    owner = cur.fetchone()
    if not owner:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Campanha não encontrada")

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
    cur = _dict_cursor(conn)

    cur.execute("SELECT * FROM campaigns WHERE id = %s", (campaign_id,))
    camp = cur.fetchone()
    if not camp:
        cur.close()
        conn.close()
        return

    cur.execute("UPDATE campaigns SET status='running' WHERE id=%s", (campaign_id,))
    conn.commit()

    template_name = camp.get("template_name")
    template_language_code = camp.get("template_language_code") or "pt_BR"
    template_body_params = camp.get("template_body_params")
    message_text = camp.get("message_text")
    phone_number_id = camp.get("phone_number_id")

    cur.execute("""
        SELECT id, "to", status
        FROM campaign_items
        WHERE campaign_id = %s AND status = 'pending'
        ORDER BY created_at ASC
    """, (campaign_id,))
    items = cur.fetchall()

    DELAY_SECONDS = 0.2
    sent = camp.get("sent", 0)
    failed = camp.get("failed", 0)

    for item in items:
        item_id = item["id"]
        to_number = item["to"]

        try:
            if template_name:
                await send_whatsapp_template(
                    to=to_number,
                    phone_number_id=phone_number_id,
                    template_name=template_name,
                    language_code=template_language_code,
                    body_params=template_body_params,
                )
            else:
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

    cur.execute("UPDATE campaigns SET status='finished' WHERE id=%s", (campaign_id,))
    conn.commit()

    cur.close()
    conn.close()
