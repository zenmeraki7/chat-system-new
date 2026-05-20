"""
SQLAlchemy model registry.

Import this module in Alembic env.py so Base.metadata contains
all mapped tables before autogenerate runs.

Do not use this module in request/runtime business logic.
"""

from app.models.business import Business
from app.models.conversation import Conversation
from app.models.message import Message
import app.models.business_domains  # noqa: F401

__all__ = [
    "Business",
    "Conversation",
    "Message",
]
