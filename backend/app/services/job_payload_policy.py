from dataclasses import dataclass
from uuid import UUID


@dataclass
class JobPayload:
    business_id: UUID
    operation_id: str
    actor_user_id: UUID | None
    idempotency_key: str


class JobPayloadPolicy:
    @staticmethod
    def validate(payload: dict) -> JobPayload:
        allowed = {"business_id", "operation_id", "actor_user_id", "idempotency_key"}
        extra = set(payload.keys()) - allowed
        if extra:
            raise ValueError(f"Job payload contains forbidden keys: {', '.join(sorted(extra))}")
        missing = [k for k in ["business_id", "operation_id", "idempotency_key"] if not payload.get(k)]
        if missing:
            raise ValueError(f"Job payload missing required keys: {', '.join(missing)}")
        return JobPayload(
            business_id=UUID(str(payload["business_id"])),
            operation_id=str(payload["operation_id"]),
            actor_user_id=UUID(str(payload["actor_user_id"])) if payload.get("actor_user_id") else None,
            idempotency_key=str(payload["idempotency_key"]),
        )
