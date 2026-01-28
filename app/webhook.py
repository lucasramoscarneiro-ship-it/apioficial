# app/webhook.py
import os
from datetime import datetime

from fastapi import APIRouter, Request
from psycopg2.extras import RealDictCursor

from .db import get_conn
from .evolution_client import send_evolution_text
from .chatbot import decide_bot_reply  # <-- você vai criar esse arquivo


router = APIRouter(prefix="/webhook", tags=["Webhook"])


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def _extract_instance_name(body: dict) -> str | None:
    return (
        body.get("instance")
        or body.get("instanceName")
        or body.get("instance_name")
        or body.get("data", {}).get("instance")
        or body.get("data", {}).get("instanceName")
        or body.get("event", {}).get("instance")
        or None
    )


def _extract_messages(body: dict) -> list[dict]:
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    msgs = data.get("messages")
    if isinstance(msgs, list):
        return [m for m in msgs if isinstance(m, dict)]
    # fallback: às vezes vem msg direto no data
    if isinstance(data, dict) and ("message" in data or "key" in data):
        return [data]
    return []


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

    # normaliza wa_id
    if from_wa and "@" in from_wa:
        from_wa = from_wa.split("@")[0]

    return from_wa, text


def _extract_timestamp(msg: dict) -> int:
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
        ts_int = int(ts)
        if ts_int > 10_000_000_000:  # ms
            ts_int //= 1000
        return ts_int
    except Exception:
        return int(datetime.utcnow().timestamp())


@router.post("")
async def evolution_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ok", "note": "invalid-json"}

    event = payload.get("event")
    instance_name = _extract_instance_name(payload)

    print("🔔 WEBHOOK RECEBIDO")
    print("Evento:", event)
    print("Instância:", instance_name)

    # A gente só trata messages.upsert
    if event != "messages.upsert":
        return {"status": "ok", "ignored": "not-messages.upsert"}

    messages = _extract_messages(payload)
    if not messages:
        return {"status": "ok", "note": "no-messages"}

    # Processa cada mensagem do batch (Evolution às vezes envia várias)
    for msg in messages:
        key = msg.get("key") or {}
        msg_id = key.get("id")
        from_me = bool(key.get("fromMe"))

        if from_me:
            # evita loop (mensagens enviadas pelo próprio bot/instância)
            continue

        from_wa, text = _extract_from_and_text(msg)
        if not from_wa or not text:
            continue

        ts = _extract_timestamp(msg)

        conn = get_conn()
        cur = _dict_cursor(conn)

        try:
            # 1) Descobrir user pelo nome da instância (se existir)
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

            # 2) Garantir conversa
            if user_id:
                cur.execute("""
                    SELECT id FROM conversations
                    WHERE wa_id = %s AND user_id = %s
                    LIMIT 1
                """, (from_wa, user_id))
            else:
                cur.execute("""
                    SELECT id FROM conversations
                    WHERE wa_id = %s AND user_id IS NULL
                    LIMIT 1
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

            # 3) DEDUPE por msg_id (idempotência)
            if msg_id:
                cur.execute(
                    "SELECT 1 FROM messages WHERE meta_message_id = %s LIMIT 1",
                    (str(msg_id),)
                )
                if cur.fetchone():
                    conn.commit()
                    continue

            # 4) Salva mensagem incoming (meta_message_id = msg_id)
            cur.execute("""
                INSERT INTO messages (
                    conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
                )
                VALUES (%s, 'incoming', 'text', %s, %s, 'received', %s, TO_TIMESTAMP(%s))
            """, (conversation_id, text, from_wa, str(msg_id) if msg_id else None, ts))

            # 5) Atualiza conversa
            cur.execute("""
                UPDATE conversations
                SET last_message_text = %s,
                    last_message_at = TO_TIMESTAMP(%s),
                    unread_count = unread_count + 1
                WHERE id = %s
            """, (text, ts, conversation_id))

            conn.commit()

        finally:
            cur.close()
            conn.close()

        # 6) CHATBOT: decide resposta e envia (fora da transação do incoming)
        try:
            bot_text = decide_bot_reply(conversation_id, text)
            if bot_text:
                instance_env = os.getenv("EVOLUTION_INSTANCE_NAME", "lucas2")

                resp = await send_evolution_text(
                    instance_name=instance_env,
                    to=from_wa,
                    text=bot_text
                )

                # opcional: salvar resposta do bot no banco (histórico)
                try:
                    bot_msg_id = None
                    if isinstance(resp, dict):
                        k = resp.get("key")
                        if isinstance(k, dict):
                            bot_msg_id = k.get("id") or None
                        else:
                            bot_msg_id = resp.get("messageId") or resp.get("id") or resp.get("msgId") or None

                    now_ts = int(datetime.utcnow().timestamp())

                    conn2 = get_conn()
                    cur2 = conn2.cursor(cursor_factory=RealDictCursor)

                    cur2.execute("""
                        INSERT INTO messages (
                            conversation_id, direction, type, text, wa_id, status, meta_message_id, timestamp
                        )
                        VALUES (%s, 'outgoing', 'text', %s, %s, 'sent', %s, TO_TIMESTAMP(%s))
                    """, (conversation_id, bot_text, from_wa, bot_msg_id, now_ts))

                    cur2.execute("""
                        UPDATE conversations
                        SET last_message_text = %s,
                            last_message_at = TO_TIMESTAMP(%s)
                        WHERE id = %s
                    """, (bot_text, now_ts, conversation_id))

                    conn2.commit()
                    cur2.close()
                    conn2.close()

                except Exception as e2:
                    print("⚠️ Não consegui salvar mensagem do bot:", str(e2))

        except Exception as e:
            print("❌ Erro chatbot:", str(e))

    return {"status": "ok"}
