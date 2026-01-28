# app/appointments_polling.py
import os
import asyncio
import random
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor

from .evolution_client import send_evolution_text


# =========================
# Helpers DB (Agendamento)
# =========================

def _dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def _get_appt_db_conn():
    """
    Conecta no banco do AGENDAMENTO (Supabase do Barbearia Cardoso),
    usando a URL completa do pooler.

    Env:
      - APPT_DATABASE_URL  (obrigatório)
      - APPT_DB_SSLMODE    (default: require)
    """
    dsn = (os.getenv("APPT_DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("Env APPT_DATABASE_URL não configurada.")

    sslmode = (os.getenv("APPT_DB_SSLMODE") or "require").strip()

    # Se o DSN já tem sslmode, não duplica
    if "sslmode=" not in dsn.lower():
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}sslmode={sslmode}"

    return psycopg2.connect(dsn, cursor_factory=RealDictCursor)


def _normalize_phone(phone: str) -> str:
    """
    Mantém somente dígitos. Tenta normalizar para padrão BR com DDI 55.
    Observação: Evolution geralmente aceita número puro com DDI.
    """
    if not phone:
        return ""
    digits = "".join([c for c in str(phone) if c.isdigit()])

    # Se veio com 11 dígitos (DDD+numero) sem 55, adiciona 55
    # Ex: 11999998888 -> 5511999998888
    if len(digits) == 11 and not digits.startswith("55"):
        digits = "55" + digits

    # Se veio com 10 dígitos (DDD+numero antigo), também adiciona 55
    if len(digits) == 10 and not digits.startswith("55"):
        digits = "55" + digits

    return digits


# =========================
# Datas / Timezone
# =========================

# Brasil -03:00 (fixo, sem depender de lib externa)
TZ_BR = timezone(timedelta(hours=-3))


def _parse_date_time_br(date_str: str, time_str: str) -> datetime | None:
    """
    Converte (data='DD/MM/YYYY' ou 'YYYY-MM-DD' ou 'DD-MM-YYYY')
    e (hora='HH:MM') em datetime com tzinfo BR (-03).
    """
    if not date_str or not time_str:
        return None

    ds = str(date_str).strip()
    ts = str(time_str).strip()

    # limpa possíveis segundos
    if len(ts) >= 5:
        ts = ts[:5]

    d = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            d = datetime.strptime(ds, fmt).date()
            break
        except Exception:
            continue
    if not d:
        return None

    try:
        t = datetime.strptime(ts, "%H:%M").time()
    except Exception:
        return None

    return datetime(d.year, d.month, d.day, t.hour, t.minute, 0, tzinfo=TZ_BR)


def _fmt_dt_br(dt: datetime) -> str:
    # garante BR
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BR)
    return dt.astimezone(TZ_BR).strftime("%d/%m/%Y %H:%M")


# =========================
# Mensagens
# =========================

def build_confirm_message(customer_name: str | None, scheduled_at: datetime, service: str | None = None) -> str:
    barber_name = os.getenv("BARBER_NAME", "Barbearia Cardoso")
    addr = (os.getenv("BARBER_ADDRESS") or "").strip()
    booking_url = (os.getenv("BOOKING_URL") or "").strip()

    name_line = f"*{customer_name}*, " if customer_name else ""
    dt_line = _fmt_dt_br(scheduled_at)

    service_line = f"\n💈 Serviço: *{service}*" if service else ""
    addr_line = f"\n📍 Endereço: {addr}" if addr else ""
    url_line = f"\n🔗 Agendamento: {booking_url}" if booking_url else ""

    return (
        f"✅ {name_line}seu agendamento na *{barber_name}* foi *confirmado*!\n\n"
        f"🗓️ Horário: *{dt_line}*"
        f"{service_line}"
        f"{addr_line}"
        f"{url_line}\n\n"
        "Qualquer dúvida, é só responder aqui. 😉"
    )


def build_reminder_message(customer_name: str | None, scheduled_at: datetime, service: str | None = None) -> str:
    barber_name = os.getenv("BARBER_NAME", "Barbearia Cardoso")
    addr = (os.getenv("BARBER_ADDRESS") or "").strip()

    name_line = f"*{customer_name}*, " if customer_name else ""
    dt_line = _fmt_dt_br(scheduled_at)
    service_line = f"\n💈 Serviço: *{service}*" if service else ""
    addr_line = f"\n📍 Endereço: {addr}" if addr else ""

    return (
        f"⏰ Lembrete: {name_line}seu horário na *{barber_name}* é em *30 minutos*.\n\n"
        f"🗓️ Horário: *{dt_line}*"
        f"{service_line}"
        f"{addr_line}\n\n"
        "Se precisar reagendar, me avise por aqui."
    )


async def _send_text(to_wa: str, text: str):
    instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "lucas2")
    await send_evolution_text(instance_name=instance_name, to=to_wa, text=text)


def _human_delay(base_min: float = 0.9, base_max: float = 2.2):
    """
    Delay humano para não ficar robotizado.
    """
    return random.uniform(base_min, base_max)


# =========================
# Queries (Tabela agendamentos)
# =========================

def _fetch_new_appointments(conn, lookback_minutes: int):
    """
    Pega agendamentos ainda não confirmados pelo bot (mensagem_enviada = false)
    e não bloqueados.

    Usa janela de lookback pra evitar perder caso o serviço reinicie.
    """
    table = os.getenv("APPT_TABLE", "agendamentos")

    # Colunas conforme seu print:
    # nome, telefone, data, hora, servico, bloqueado, criado_em, mensagem_enviada, reminder_enviado
    sql = f"""
        SELECT
          id,
          nome,
          telefone,
          data,
          hora,
          servico,
          bloqueado,
          criado_em,
          mensagem_enviada,
          reminder_enviado
        FROM {table}
        WHERE COALESCE(bloqueado, false) = false
          AND COALESCE(mensagem_enviada, false) = false
          AND criado_em >= (NOW() - (%s || ' minutes')::interval)
        ORDER BY criado_em ASC
        LIMIT 200
    """
    cur = _dict_cursor(conn)
    cur.execute(sql, (str(lookback_minutes),))
    return cur.fetchall() or []


def _fetch_due_reminders(conn, now_br: datetime, reminder_minutes: int):
    """
    Busca agendamentos que:
      - reminder_enviado = false
      - bloqueado = false
      - horário do agendamento está entre (agora + 30min) com tolerância (janela)
    Como data/hora são text, fazemos parsing em Python (mais confiável do que SQL aqui).
    """
    table = os.getenv("APPT_TABLE", "agendamentos")

    sql = f"""
        SELECT
          id,
          nome,
          telefone,
          data,
          hora,
          servico,
          bloqueado,
          criado_em,
          mensagem_enviada,
          reminder_enviado
        FROM {table}
        WHERE COALESCE(bloqueado, false) = false
          AND COALESCE(reminder_enviado, false) = false
        ORDER BY criado_em DESC
        LIMIT 500
    """
    cur = _dict_cursor(conn)
    cur.execute(sql)
    rows = cur.fetchall() or []

    # janela: envia se está faltando entre 29 e 31 minutos (tolerância)
    # e evita mandar lembrete para agendamento já passado
    target_min = reminder_minutes - 1
    target_max = reminder_minutes + 1

    due = []
    for r in rows:
        dt = _parse_date_time_br(r.get("data"), r.get("hora"))
        if not dt:
            continue

        delta = dt - now_br
        mins = delta.total_seconds() / 60.0

        if target_min <= mins <= target_max:
            due.append((r, dt))

    return due


def _mark_confirm_sent(conn, appt_id):
    table = os.getenv("APPT_TABLE", "agendamentos")
    sql = f"""
        UPDATE {table}
        SET mensagem_enviada = true
        WHERE id = %s
          AND COALESCE(mensagem_enviada, false) = false
    """
    cur = _dict_cursor(conn)
    cur.execute(sql, (str(appt_id),))


def _mark_reminder_sent(conn, appt_id):
    table = os.getenv("APPT_TABLE", "agendamentos")
    sql = f"""
        UPDATE {table}
        SET reminder_enviado = true
        WHERE id = %s
          AND COALESCE(reminder_enviado, false) = false
    """
    cur = _dict_cursor(conn)
    cur.execute(sql, (str(appt_id),))


# =========================
# Poller principal
# =========================

async def appointments_poller(stop_event: asyncio.Event):
    """
    Loop que:
    1) Detecta agendamentos novos (mensagem_enviada=false) e envia confirmação (1x)
    2) Envia lembrete 30 min antes (1x)
    Marcando no PRÓPRIO banco de agendamentos:
      - mensagem_enviada = true
      - reminder_enviado = true

    Env:
      - APPT_POLL_SECONDS (default 15)
      - APPT_LOOKBACK_MINUTES (default 1440)
      - APPT_REMINDER_MINUTES (default 30)
      - APPT_DATABASE_URL (obrigatório)
      - APPT_DB_SSLMODE (default require)
      - APPT_TABLE (default agendamentos)
    """
    interval = int(os.getenv("APPT_POLL_SECONDS", "15"))
    lookback_minutes = int(os.getenv("APPT_LOOKBACK_MINUTES", "1440"))  # 24h padrão
    reminder_minutes = int(os.getenv("APPT_REMINDER_MINUTES", "30"))

    print(f"[APPT] Poller iniciado. Interval={interval}s Lookback={lookback_minutes}min Reminder={reminder_minutes}min")

    while not stop_event.is_set():
        try:
            now_br = datetime.now(TZ_BR)

            # Conecta uma vez por ciclo (mais simples e robusto)
            conn = _get_appt_db_conn()
            try:
                # 1) Confirmações pendentes
                new_rows = _fetch_new_appointments(conn, lookback_minutes=lookback_minutes)

                for appt in new_rows:
                    appt_id = appt.get("id")
                    nome = appt.get("nome")
                    telefone = _normalize_phone(appt.get("telefone"))
                    servico = appt.get("servico")

                    scheduled_at = _parse_date_time_br(appt.get("data"), appt.get("hora"))
                    if not appt_id or not telefone or not scheduled_at:
                        continue

                    # humaniza
                    await asyncio.sleep(_human_delay(1.0, 2.4))

                    # envia confirmação
                    text_confirm = build_confirm_message(nome, scheduled_at, servico)
                    await _send_text(telefone, text_confirm)

                    # marca como enviada (idempotência)
                    _mark_confirm_sent(conn, appt_id)
                    conn.commit()

                # 2) Lembretes 30 min antes
                due = _fetch_due_reminders(conn, now_br=now_br, reminder_minutes=reminder_minutes)

                for (appt, scheduled_at) in due:
                    appt_id = appt.get("id")
                    nome = appt.get("nome")
                    telefone = _normalize_phone(appt.get("telefone"))
                    servico = appt.get("servico")

                    if not appt_id or not telefone:
                        continue

                    await asyncio.sleep(_human_delay(0.8, 2.0))

                    text_rem = build_reminder_message(nome, scheduled_at, servico)
                    await _send_text(telefone, text_rem)

                    _mark_reminder_sent(conn, appt_id)
                    conn.commit()

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print("[APPT] Erro no poller:", str(e))

        # dorme até o próximo ciclo, mas encerra rápido se pedirem stop
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
