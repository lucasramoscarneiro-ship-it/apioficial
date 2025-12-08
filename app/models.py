from pydantic import BaseModel
from typing import Optional, Dict, List
from enum import Enum
from datetime import datetime
import uuid

# =======================
# "BANCO" EM MEMÓRIA
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
    wa_id: str              # telefone no formato Meta (55119...)
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
    def create_outgoing(cls, conversation_id: str, text: str, meta_message_id: str):
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
        # Meta manda timestamp em segundos → convertemos para datetime
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


class SendTextRequest(BaseModel):
    phone_number_id: str    # PHONE_NUMBER_ID da Meta
    to: str                 # telefone destino (55119...)
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
# =======================

class CampaignStatus(str, Enum):
    pending = "pending"
    running = "running"
    finished = "finished"
    failed = "failed"


class Campaign(BaseModel):
    id: str
    name: str
    phone_number_id: str

    # Se for template oficial:
    template_name: Optional[str] = None
    template_language_code: Optional[str] = "pt_BR"
    template_body_params: Optional[List[str]] = None  # para {{1}}, {{2}}, etc.

    # Se for texto livre:
    message_text: Optional[str] = None

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
    phone_number_id: str

    # OU template oficial:
    template_name: Optional[str] = None
    template_language_code: Optional[str] = "pt_BR"
    template_body_params: Optional[List[str]] = None

    # OU mensagem de texto livre:
    message_text: Optional[str] = None

    # Lista de números (55119...)
    to_numbers: List[str]
