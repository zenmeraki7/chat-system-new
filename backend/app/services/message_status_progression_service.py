from datetime import datetime
from app.models.message import Message, MessageStatus


_STATUS_RANK = {
    MessageStatus.QUEUED.value: 10,
    MessageStatus.SENDING.value: 20,
    MessageStatus.SENT.value: 30,
    MessageStatus.DELIVERED.value: 40,
    MessageStatus.READ.value: 50,
    MessageStatus.FAILED.value: 60,
    MessageStatus.CANCELLED.value: 70,
}


class MessageStatusProgressionService:
    @staticmethod
    def apply_if_newer(message: Message, incoming_status: str, provider_timestamp: datetime | None = None) -> bool:
        current = (message.status.value if hasattr(message.status, "value") else str(message.status or "queued")).lower()
        incoming = incoming_status.lower()
        if incoming not in _STATUS_RANK:
            return False

        if _STATUS_RANK[incoming] < _STATUS_RANK.get(current, 0):
            return False

        if incoming in {MessageStatus.DELIVERED.value, MessageStatus.READ.value} and current == MessageStatus.FAILED.value:
            return False

        message.status = MessageStatus(incoming)
        if incoming == MessageStatus.SENT.value:
            message.sent_at = provider_timestamp or datetime.utcnow()
        elif incoming == MessageStatus.DELIVERED.value:
            message.delivered_at = provider_timestamp or datetime.utcnow()
        elif incoming == MessageStatus.READ.value:
            message.read_at = provider_timestamp or datetime.utcnow()
        elif incoming == MessageStatus.FAILED.value:
            message.failed_at = provider_timestamp or datetime.utcnow()
        return True
