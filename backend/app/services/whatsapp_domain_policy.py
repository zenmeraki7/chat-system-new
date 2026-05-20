from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TemplateCategory = Literal["marketing", "utility", "authentication"]
ConversationClass = Literal["session_customer_service", "template_marketing", "template_utility", "template_authentication", "service_conversation"]


@dataclass(frozen=True)
class MessageClassification:
    conversation_class: ConversationClass
    requires_template_approval: bool


class WhatsAppDomainPolicy:
    @staticmethod
    def classify(template_category: str | None) -> MessageClassification:
        if not template_category:
            return MessageClassification(
                conversation_class="session_customer_service",
                requires_template_approval=False,
            )
        category = template_category.strip().lower()
        if category == "marketing":
            return MessageClassification("template_marketing", True)
        if category == "utility":
            return MessageClassification("template_utility", True)
        if category == "authentication":
            return MessageClassification("template_authentication", True)
        return MessageClassification("service_conversation", True)


whatsapp_domain_policy = WhatsAppDomainPolicy()

