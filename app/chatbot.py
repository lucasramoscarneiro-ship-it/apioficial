import os
import re
import random
from datetime import datetime, date

from .db import get_conn
from psycopg2.extras import RealDictCursor


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def is_greeting(t: str) -> bool:
    greetings = [
        "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite",
        "eai", "e aí", "fala", "inicio", "menu", "começar", "comecar"
    ]
    return any(t == g or t.startswith(g + " ") for g in greetings)


# =========================
# Anti-spam / humanização
# =========================

def _rand(a: float, b: float) -> float:
    try:
        return random.uniform(a, b)
    except Exception:
        return a


def _soften(text: str) -> str:
    """
    Pequena variação de texto (sem exagerar) pra não ficar sempre igual.
    """
    variants = [
        text,
        text.replace("✅", "✅"),
        text.replace("Perfeito!", "Show!"),
        text.replace("Perfeito!", "Beleza!"),
        text.replace("Se quiser voltar ao menu, digite *menu*.", "Pra voltar ao menu, é só digitar *menu*."),
    ]
    return random.choice(variants)


def _recommended_delay_seconds(kind: str) -> float:
    """
    Retorna um "tempo humano" recomendado (em segundos) para a camada de envio.
    OBS: O delay de verdade deve ser aplicado no webhook (antes de enviar),
    aqui só sugerimos/colocamos junto do texto com marcador.
    """
    # tempos pequenos e naturais (evita rajada)
    if kind == "greeting":
        return _rand(1.2, 2.4)
    if kind == "menu":
        return _rand(0.8, 1.8)
    if kind == "option":
        return _rand(0.7, 1.6)
    return _rand(0.6, 1.4)


def wrap_with_delay(text: str, kind: str) -> str:
    """
    Embute um marcador que você pode usar no webhook para aplicar await asyncio.sleep(...)
    Exemplo de leitura no webhook:
      if bot_text.startswith("__DELAY__="): ...
    """
    delay = _recommended_delay_seconds(kind)
    return f"__DELAY__={delay:.2f}__\n{text}"


# =========================
# Mensagens
# =========================

def build_greeting_message() -> str:
    barber_name = os.getenv("BARBER_NAME", "Barbearia Cardoso")
    booking_url = os.getenv("BOOKING_URL", "https://agendacardoso.streamlit.app/").strip()
    addr = os.getenv("BARBER_ADDRESS", "").strip()

    hello_lines = [
        f"✨ Olá! Seja bem-vindo(a) à *{barber_name}* 💈",
        f"👋 Oi! Você falou com a *{barber_name}* 💈",
        f"😄 Olá! Que bom te ver por aqui na *{barber_name}* 💈",
    ]
    hello = random.choice(hello_lines)

    link_line = f"📅 *Agende agora:* {booking_url}\n" if booking_url else ""
    addr_line = f"📍 *Endereço:* {addr}\n" if addr else ""

    msg = (
        f"{hello}\n\n"
        f"{link_line}"
        f"{addr_line}\n"
        "Pra facilitar, aqui vai nosso menu rápido:\n"
        "1) Agendamento\n"
        "2) Endereço / Como chegar\n"
        "3) Horários de funcionamento\n"
        "4) Valores / Serviços\n"
        "5) Falar com um atendente\n\n"
        "Responda com *1, 2, 3, 4* ou *5*."
    )
    return msg


def build_menu_message() -> str:
    barber_name = os.getenv("BARBER_NAME", "Barbearia Cardoso")
    booking_url = os.getenv("BOOKING_URL", "https://agendacardoso.streamlit.app/").strip()

    link_line = f"📅 Agende aqui: {booking_url}\n\n" if booking_url else ""
    return (
        f"Como posso te ajudar na *{barber_name}*? 💈\n\n"
        f"{link_line}"
        "1) Agendamento\n"
        "2) Endereço / Como chegar\n"
        "3) Horários de funcionamento\n"
        "4) Valores / Serviços\n"
        "5) Falar com um atendente\n\n"
        "Responda com *1, 2, 3, 4* ou *5*."
    )


def build_booking_message() -> str:
    booking_url = os.getenv("BOOKING_URL", "https://agendacardoso.streamlit.app/").strip()
    if booking_url:
        return _soften(
            "Perfeito! ✅\n"
            f"📅 Para agendar, acesse: {booking_url}\n\n"
            "Se quiser voltar ao menu, digite *menu*."
        )
    return _soften(
        "Perfeito! ✅\n"
        "No momento o link de agendamento não está configurado.\n"
        "Me diga seu *nome* e o *horário desejado* que um atendente te ajuda.\n\n"
        "Digite *menu* para voltar."
    )


def build_address_message() -> str:
    addr = os.getenv("BARBER_ADDRESS", "").strip() or "Endereço ainda não configurado."
    return (
        f"📍 Endereço:\n{addr}\n\n"
        "Se quiser voltar ao menu, digite *menu*."
    )


def build_hours_message() -> str:
    hours = os.getenv("BARBER_HOURS", "").strip() or "Horários ainda não configurados."
    return (
        f"🕒 Horários:\n{hours}\n\n"
        "Se quiser voltar ao menu, digite *menu*."
    )


def build_prices_message() -> str:
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


# =========================
# Sessão (chatbot_sessions)
# =========================

def get_session_state(conversation_id: str) -> dict:
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        SELECT conversation_id, state, last_intent, last_greeting_date, updated_at
        FROM chatbot_sessions
        WHERE conversation_id = %s
        LIMIT 1
    """, (conversation_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def upsert_session(conversation_id: str, state: str, last_intent: str | None = None, last_greeting_date=None):
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute("""
        INSERT INTO chatbot_sessions (conversation_id, state, last_intent, last_greeting_date, updated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (conversation_id)
        DO UPDATE SET state = EXCLUDED.state,
                      last_intent = EXCLUDED.last_intent,
                      last_greeting_date = COALESCE(EXCLUDED.last_greeting_date, chatbot_sessions.last_greeting_date),
                      updated_at = NOW()
    """, (conversation_id, state, last_intent, last_greeting_date))
    conn.commit()
    cur.close()
    conn.close()


# =========================
# Core decisão do bot
# =========================

def decide_bot_reply(conversation_id: str, user_text: str) -> str | None:
    """
    Retorna a resposta do bot ou None (se não deve responder).

    REGRAS:
    - Primeiro contato do DIA (saudação): manda saudação bonita + link + endereço + menu (uma vez por dia)
    - Mesmo dia: não manda saudação novamente; manda menu
    - Opções 1..5: responde normalmente
    - Fallback: se esperando opção, orienta
    """
    t = normalize_text(user_text)
    today = date.today()

    # sessão atual
    sess = get_session_state(conversation_id)
    last_greet = sess.get("last_greeting_date") if sess else None
    last_greet_str = str(last_greet) if last_greet is not None else ""

    # comandos globais
    if t in ("menu", "inicio", "início", "começar", "comecar"):
        upsert_session(conversation_id, "awaiting_option", "menu")
        return wrap_with_delay(build_menu_message(), "menu")

    # saudação / primeiro contato do dia
    if is_greeting(t):
        # se ainda não saudou hoje => manda greeting completo
        if last_greet_str != str(today):
            upsert_session(conversation_id, "awaiting_option", "greeting_today", last_greeting_date=today)
            return wrap_with_delay(build_greeting_message(), "greeting")

        # já saudou hoje => manda menu (sem repetir saudação)
        upsert_session(conversation_id, "awaiting_option", "menu_same_day")
        return wrap_with_delay(build_menu_message(), "menu")

    # opções numéricas
    if t in ("1", "01"):
        upsert_session(conversation_id, "idle", "booking")
        return wrap_with_delay(build_booking_message(), "option")

    if t in ("2", "02"):
        upsert_session(conversation_id, "idle", "address")
        return wrap_with_delay(build_address_message(), "option")

    if t in ("3", "03"):
        upsert_session(conversation_id, "idle", "hours")
        return wrap_with_delay(build_hours_message(), "option")

    if t in ("4", "04"):
        upsert_session(conversation_id, "idle", "prices")
        return wrap_with_delay(build_prices_message(), "option")

    if t in ("5", "05", "atendente", "humano", "falar com atendente", "falar com humano"):
        upsert_session(conversation_id, "handoff", "human")
        return wrap_with_delay(build_human_message(), "option")

    # fallback
    if not sess:
        # se ainda não existe sessão, cria e manda menu (sem spammar)
        upsert_session(conversation_id, "awaiting_option", "fallback_menu")
        return wrap_with_delay(build_menu_message(), "menu")

    if sess.get("state") == "awaiting_option":
        return wrap_with_delay(
            "Não entendi 😅\n\n"
            "Responda com *1, 2, 3, 4* ou *5*.\n"
            "Ou digite *menu* para ver as opções.",
            "menu",
        )

    # se já está idle/handoff, não responde automaticamente
    return None
