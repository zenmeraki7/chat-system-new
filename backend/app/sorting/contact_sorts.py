from __future__ import annotations

from sqlalchemy import func

from app.models.business_domains import Contact


CONTACT_SORTS = {
    "updated_at": {
        "column": Contact.updated_at,
        "model_attr": "updated_at",
        "default_dir": "desc",
        "nullable": False,
        "cursor_type": "datetime",
    },
    "created_at": {
        "column": Contact.created_at,
        "model_attr": "created_at",
        "default_dir": "desc",
        "nullable": False,
        "cursor_type": "datetime",
    },
    "name": {
        "column": func.lower(func.coalesce(Contact.display_name, "")),
        "model_attr": "display_name",
        "default_dir": "asc",
        "nullable": False,
        "cursor_type": "string",
    },
    "phone_number": {
        "column": func.coalesce(Contact.normalized_phone, ""),
        "model_attr": "normalized_phone",
        "default_dir": "asc",
        "nullable": False,
        "cursor_type": "string",
    },
}

