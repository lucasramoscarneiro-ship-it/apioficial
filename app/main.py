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

# ✅ SOMENTE EVOLUTION
from .models import SendTextRequest, CampaignCreate
from .politica import router as politica_router
from .termos import router as termos_router
from .auth.auth_router import router as auth_router
from .auth.dependencies import get_current_user
from .evolution_client import send_evolution_text


app = FastAPI(title="Painel WhatsApp LRC")

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
    Envia mensagem SOMENTE via Evolution.
    Salva no banco e atualiza a conversa.
    """
    user_id = _get_user_id(user)

    # Normaliza o "to" (remove @s.whatsapp.net se vier)
    to_wa = (payload.to or "").strip()
    if "@s.whatsapp.net" in to_wa:
        to_wa = to_wa.split("@")[0]

    if not to_wa:
        raise HTTPException(status_code=400, detail="Campo 'to' inválido")

    conn = get_conn()
    cur = _dict_cursor(conn)

    # conversa precisa pertencer ao usuário
    # (e se por algum motivo veio user_id NULL do webhook, permitimos também)
    cur.execute("""
        SELECT id
        FROM conversations
        WHERE wa_id = %s AND (user_id = %s OR user_id IS NULL)
        LIMIT 1
    """, (to_wa, user_id))
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Conversa não encontrada para este usuário")

    conversation_id = row["id"]

    # =========================
    # ENVIO (EVOLUTION)
    # =========================
    provider = "evolution"
    provider_message_id = None
    resp = None

    try:
        instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "lucas2")

        resp = await send_evolution_text(
            instance_name=instance_name,
            to=to_wa,
            text=payload.message
        )

        # tenta pegar algum id retornado
        if isinstance(resp, dict):
            provider_message_id = (
                resp.get("key", "")
                or resp.get("messageId", "")
                or resp.get("id", "")
                or resp.get("msgId", "")
                or None
            )

    except Exception as e:
        cur.close()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Falha ao enviar (evolution): {str(e)}")

    now_ts = int(datetime.utcnow().timestamp())

    # salva mensagem enviada (outgoing)
    cur.execute("""
        INSERT INTO messages (
            conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
        )
        VALUES (%s, 'outgoing', 'text', %s, %s, 'sent', %s, TO_TIMESTAMP(%s))
        RETURNING id
    """, (conversation_id, payload.message, to_wa, provider_message_id, now_ts))
    msg_row = cur.fetchone()

    # atualiza conversa
    cur.execute("""
        UPDATE conversations
        SET last_message_text = %s,
            last_message_at = TO_TIMESTAMP(%s)
        WHERE id = %s
    """, (payload.message, now_ts, conversation_id))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "sent",
        "conversation_id": conversation_id,
        "message_id": msg_row["id"],
        "provider": provider,
        "provider_message_id": provider_message_id,
        "provider_response": resp
    }


# =======================
# WEBHOOK EVOLUTION - NÃO PROTEGIDO
# =======================

def _extract_evolution_instance_name(body: dict) -> str | None:
    # tenta achar o nome da instância em vários formatos
    return (
        body.get("instance")
        or body.get("instanceName")
        or body.get("instance_name")
        or body.get("data", {}).get("instance")
        or body.get("data", {}).get("instanceName")
        or body.get("event", {}).get("instance")
        or None
    )


def _extract_evolution_message(body: dict) -> dict | None:
    data = body.get("data")
    if not isinstance(data, dict):
        return None

    # Evolution padrão
    # data = { "messages": [ { ... } ] }
    if "messages" in data and isinstance(data["messages"], list) and data["messages"]:
        return data["messages"][0]

    # fallback
    return data


def _extract_from_and_text(msg: dict) -> tuple[str | None, str | None]:
    from_wa = (
        msg.get("from")
        or msg.get("key", {}).get("remoteJid")
        or msg.get("remoteJid")
    )

    text = None

    message = msg.get("message", {}) or {}
    if isinstance(message, dict):
        if "conversation" in message:
            text = message["conversation"]
        elif "extendedTextMessage" in message and isinstance(message["extendedTextMessage"], dict):
            text = message["extendedTextMessage"].get("text")

    return from_wa, text


def _extract_timestamp(msg: dict) -> int:
    # tenta extrair timestamp; fallback agora
    ts = (
        msg.get("timestamp")
        or msg.get("messageTimestamp")
        or msg.get("messageTimestampMs")
        or msg.get("time")
        or None
    )
    try:
        if ts is None:
            return int(datetime.utcnow().timestamp())
        # se vier em ms
        ts_int = int(ts)
        if ts_int > 10_000_000_000:  # > ~2286-11 em segundos -> provavelmente ms
            ts_int = ts_int // 1000
        return ts_int
    except Exception:
        return int(datetime.utcnow().timestamp())


@app.post("/webhook/evolution")
async def receive_evolution_webhook(request: Request):
    # sempre define body antes de usar
    try:
        body = await request.json()
        print("=== EVOLUTION WEBHOOK HIT ===")
        print("event:", body.get("event"))
        print("EVOLUTION SERVER_URL:", body.get("server_url"))

    except Exception as e:
        print("❌ ERRO lendo JSON do webhook:", str(e))
        return {"status": "ok", "note": "invalid-json"}

    print("=== EVOLUTION WEBHOOK HIT ===")
    print("keys:", list(body.keys()))
    print("event:", body.get("event"))

    # 1) Pega instância e mensagem
    instance_name = _extract_evolution_instance_name(body)
    msg = _extract_evolution_message(body)

    if not msg or not isinstance(msg, dict):
        return {"status": "ok", "note": "no-message"}

    from_wa, text = _extract_from_and_text(msg)

    # normaliza wa_id
    if from_wa and "@" in from_wa:
        from_wa = from_wa.split("@")[0]

    if not from_wa or not text:
        return {"status": "ok", "note": "no-text-or-from"}

    ts = _extract_timestamp(msg)

    conn = get_conn()
    cur = _dict_cursor(conn)

    # 2) Descobrir user pelo nome da instância (se existir)
    user_id = None
    if instance_name:
        try:
            cur.execute("""
                SELECT id FROM users
                WHERE evolution_instance_name = %s AND is_active = true
                LIMIT 1
            """, (str(instance_name),))
            u = cur.fetchone()
            if u:
                user_id = str(u["id"])
        except Exception:
            user_id = None

    # 3) Garante conversa
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

    # 4) Insere mensagem
    cur.execute("""
        INSERT INTO messages (
            conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
        )
        VALUES (%s, 'incoming', 'text', %s, %s, 'received', NULL, TO_TIMESTAMP(%s))
    """, (conversation_id, text, from_wa, ts))

    # 5) Atualiza conversa (SQL correto)
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
# CAMPANHAS (DISPARO EM MASSA) - PROTEGIDO (SOMENTE EVOLUTION)
# =======================

@app.post("/api/campaigns")
async def create_campaign(payload: CampaignCreate, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    """
    Cria campanha do usuário logado e dispara em background (SOMENTE TEXTO via Evolution).
    """
    user_id = _get_user_id(user)

    if not payload.message_text:
        return {"error": "Informe message_text."}

    conn = get_conn()
    cur = _dict_cursor(conn)

    # phone_number_id / template removidos
    cur.execute("""
        INSERT INTO campaigns (
            user_id,
            name,
            template_name,
            template_language_code,
            template_body_params,
            message_text,
            total,
            sent,
            failed,
            status
        )
        VALUES (%s, %s, NULL, NULL, NULL, NULL, %s, %s, 0, 0, 'pending')
        RETURNING id
    """, (
        user_id,
        payload.name,
        payload.message_text,
        len(payload.to_numbers),
    ))
    row = cur.fetchone()
    campaign_id = row["id"]

    for num in payload.to_numbers:
        num_clean = (num or "").strip()
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
        SELECT id, name, message_text, total, sent, failed, status, created_at
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
    Envia as mensagens de uma campanha em background (SOMENTE Evolution).
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

    message_text = camp.get("message_text") or ""

    cur.execute("""
        SELECT id, "to", status
        FROM campaign_items
        WHERE campaign_id = %s AND status = 'pending'
        ORDER BY created_at ASC
    """, (campaign_id,))
    items = cur.fetchall()

    DELAY_SECONDS = 0.2
    sent = camp.get("sent", 0) or 0
    failed = camp.get("failed", 0) or 0

    instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "lucas2")

    for item in items:
        item_id = item["id"]
        to_number = item["to"]

        try:
            await send_evolution_text(
                instance_name=instance_name,
                to=to_number,
                text=message_text,
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
