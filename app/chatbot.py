import os
import re
from datetime import datetime

from .db import get_conn
from psycopg2.extras import RealDictCursor


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    # remove excesso de espaços
    s = re.sub(r"\s+", " ", s)
    return s


def is_greeting(t: str) -> bool:
    # gatilhos simples
    greetings = [
        "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite",
        "eai", "e aí", "fala", "inicio", "menu", "começar", "comecar"
    ]
    return any(t == g or t.startswith(g + " ") for g in greetings)


def build_menu_message() -> str:
    barber_name = os.getenv("BARBER_NAME", "Barbearia")
    booking_url = os.getenv("BOOKING_URL", "").strip()

    link_line = f"📅 Agende aqui: {booking_url}\n\n" if booking_url else ""
    return (
        f"👋 Olá! Você está falando com a *{barber_name}*.\n\n"
        f"{link_line}"
        "Como posso te ajudar?\n"
        "1) Agendamento\n"
        "2) Endereço / Como chegar\n"
        "3) Horários de funcionamento\n"
        "4) Valores / Serviços\n"
        "5) Falar com um atendente\n\n"
        "Responda com *1, 2, 3, 4* ou *5*."
    )


def build_booking_message() -> str:
    booking_url = os.getenv("BOOKING_URL", "").strip()
    if booking_url:
        return (
            "Perfeito! ✅\n"
            f"📅 Para agendar, acesse: {booking_url}\n\n"
            "Se quiser voltar ao menu, digite *menu*."
        )
    return (
        "Perfeito! ✅\n"
        "No momento o link de agendamento não está configurado.\n"
        "Me diga seu *nome* e o *horário desejado* que um atendente te ajuda.\n\n"
        "Digite *menu* para voltar."
    )


def build_address_message() -> str:
    addr = os.getenv("BARBER_ADDRESS", "").strip()
    if not addr:
        addr = "Endereço ainda não configurado."
    return (
        f"📍 Endereço:\n{addr}\n\n"
        "Se quiser voltar ao menu, digite *menu*."
    )


def build_hours_message() -> str:
    hours = os.getenv("BARBER_HOURS", "").strip()
    if not hours:
        hours = "Horários ainda não configurados."
    return (
        f"🕒 Horários:\n{hours}\n\n"
        "Se quiser voltar ao menu, digite *menu*."
    )


def build_prices_message() -> str:
    # Você pode trocar esse texto por algo do seu cardápio real
    return (
        "💈 Valores / Serviços (exemplo):\n"
        "• Corte: R$ XX\n"
        "• Barba: R$ XX\n"
        "• Corte + Barba: R$ XX\n"
        "• Sobrancelha: R$ XX\n\n"
        "Quer agendar? Responda *1*.\n"
        "Voltar ao menu: digite *menu*."
    )


def build_human_message() -> str:
    return (
        "✅ Certo! Vou chamar um atendente.\n"
        "Por favor, envie:\n"
        "• Seu *nome*\n"
        "• O serviço desejado\n"
        "• Melhor horário\n\n"
        "Voltar ao menu: digite *menu*."
    )


def get_session_state(conversation_id: str) -> dict:
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        SELECT conversation_id, state, last_intent, updated_at
        FROM chatbot_sessions
        WHERE conversation_id = %s
        LIMIT 1
    """, (conversation_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def upsert_session(conversation_id: str, state: str, last_intent: str | None = None):
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        INSERT INTO chatbot_sessions (conversation_id, state, last_intent, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (conversation_id)
        DO UPDATE SET state = EXCLUDED.state,
                      last_intent = EXCLUDED.last_intent,
                      updated_at = NOW()
    """, (conversation_id, state, last_intent))
    conn.commit()
    cur.close()
    conn.close()


def decide_bot_reply(conversation_id: str, user_text: str) -> str | None:
    """
    Retorna a resposta do bot ou None (se não deve responder).
    """
    t = normalize_text(user_text)

    # comandos globais
    if t in ("menu", "inicio", "início", "começar", "comecar"):
        upsert_session(conversation_id, "awaiting_option", "menu")
        return build_menu_message()

    # saudação
    if is_greeting(t):
        upsert_session(conversation_id, "awaiting_option", "greeting")
        return build_menu_message()

    # opções numéricas
    if t in ("1", "01"):
        upsert_session(conversation_id, "idle", "booking")
        return build_booking_message()

    if t in ("2", "02"):
        upsert_session(conversation_id, "idle", "address")
        return build_address_message()

    if t in ("3", "03"):
        upsert_session(conversation_id, "idle", "hours")
        return build_hours_message()

    if t in ("4", "04"):
        upsert_session(conversation_id, "idle", "prices")
        return build_prices_message()

    if t in ("5", "05", "atendente", "humano", "falar com atendente", "falar com humano"):
        upsert_session(conversation_id, "handoff", "human")
        return build_human_message()

    # fallback: se o usuário mandou algo aleatório, manda menu (mas sem spammar demais)
    # regra simples: se não tem sessão ainda, ou se estava aguardando opção, reenvia menu
    sess = get_session_state(conversation_id)
    if not sess:
        upsert_session(conversation_id, "awaiting_option", "fallback_menu")
        return build_menu_message()

    if sess.get("state") == "awaiting_option":
        return (
            "Não entendi 😅\n\n"
            "Responda com *1, 2, 3, 4* ou *5*.\n"
            "Ou digite *menu* para ver as opções."
        )

    # se já está idle/handoff, não responde automaticamente
    return None
