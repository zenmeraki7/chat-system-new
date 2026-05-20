"""
Minimal model package exports.

Do not import all ORM models here.
Use app.models.registry for Alembic/model discovery.
Use direct model-module imports in application code.
"""

from app.models.base import BaseModel

__all__ = ["BaseModel"]
