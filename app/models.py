from pydantic import BaseModel
from typing import Optional, Dict, List
from enum import Enum
from datetime import datetime
import uuid

# =======================
# "BANCO" EM MEMÓRIA
# (mantive porque já existe no seu projeto; mesmo que você use Postgres,
#  esses modelos ainda servem para validação / tipagem)
# =======================

conversations_db: Dict[str, "Conversation"] = {}
messages_db: Dict[str, "Message"] = {}

campaigns_db: Dict[str, "Campaign"] = {}
campaign_items_db: Dict[str, "CampaignItem"] = {}

# =======================
# MODELOS DE CHAT
# =======================

class Conversation(BaseModel):
    id: str
    wa_id: str              # telefone (55119...)
    name: Optional[str] = None
    last_message_text: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0


class Message(BaseModel):
    id: str
    conversation_id: str
    direction: str          # "incoming" ou "outgoing"
    type: str               # "text", "image"... (por enquanto só text)
    text: Optional[str] = None
    wa_id: Optional[str] = None   # telefone do cliente
    status: str = "sent"    # sent / received / read / failed
    meta_message_id: Optional[str] = None
    timestamp: datetime

    @classmethod
    def create_outgoing(cls, conversation_id: str, text: str, meta_message_id: str | None = None):
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            direction="outgoing",
            type="text",
            text=text,
            status="sent",
            meta_message_id=meta_message_id,
            timestamp=datetime.utcnow()
        )

    @classmethod
    def create_incoming(cls, conversation_id: str, text: str, wa_id: str, timestamp: int):
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            direction="incoming",
            type="text",
            text=text,
            wa_id=wa_id,
            status="received",
            timestamp=datetime.fromtimestamp(timestamp)
        )


# =======================
# REQUEST DE ENVIO (CHAT)
# - SOMENTE EVOLUTION
# =======================

class SendTextRequest(BaseModel):
    to: str                 # telefone destino (55119... ou 55119...@s.whatsapp.net)
    message: str            # texto da mensagem


def create_or_get_conversation(wa_id: str) -> Conversation:
    """
    Se já existir conversa com esse wa_id, retorna.
    Senão, cria uma nova.
    """
    for conv in conversations_db.values():
        if conv.wa_id == wa_id:
            return conv

    conv = Conversation(
        id=str(uuid.uuid4()),
        wa_id=wa_id,
        name=wa_id,
        last_message_text=None,
        last_message_at=None,
        unread_count=0,
    )
    conversations_db[conv.id] = conv
    return conv


# =======================
# MODELOS DE CAMPANHA
# - SOMENTE EVOLUTION (TEXTO)
# =======================

class CampaignStatus(str, Enum):
    pending = "pending"
    running = "running"
    finished = "finished"
    failed = "failed"


class Campaign(BaseModel):
    id: str
    name: str

    # SOMENTE texto livre (Evolution)
    message_text: str

    total: int = 0
    sent: int = 0
    failed: int = 0
    status: CampaignStatus = CampaignStatus.pending


class CampaignItemStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class CampaignItem(BaseModel):
    id: str
    campaign_id: str
    to: str
    status: CampaignItemStatus = CampaignItemStatus.pending
    error_message: Optional[str] = None


class CampaignCreate(BaseModel):
    name: str

    # SOMENTE mensagem de texto (Evolution)
    message_text: str

    # Lista de números (55119...)
    to_numbers: List[str]
