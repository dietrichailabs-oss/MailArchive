from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VerificationStatus(str, Enum):
    PENDING = 'PENDING'
    VERIFIED = 'VERIFIED'
    FAILED = 'FAILED'


@dataclass(frozen=True)
class MessageRef:
    provider_id: str
    folder_id: str
    internet_message_id: Optional[str] = None


@dataclass
class ProviderMessage:
    ref: MessageRef
    subject: str = ''
    sender: str = ''
    recipients: list[str] = field(default_factory=list)
    received_ts: str = ''
    sent_ts: str = ''
    size_hint: int | None = None
