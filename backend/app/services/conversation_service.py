from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.exceptions import ForbiddenException, NotFoundException, ConflictException
from app.models.conversation import Conversation
from app.models.business_domains import (
    ConversationStatusEvent,
    OutboxEvent,
    ConversationAssignment,
    SlaPolicy,
    TeamMember,
    Agent,
)
from app.services.audit_log_service import AuditLogService


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditLogService(db)

    async def _get_for_business(self, business_id: UUID, conversation_id: UUID) -> Conversation:
        row = await self.db.execute(
            select(Conversation).where(
                Conversation.business_id == business_id,
                Conversation.id == conversation_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conversation = row.scalar_one_or_none()
        if not conversation:
            raise NotFoundException("Conversation not found")
        return conversation

    async def _transition(self, business_id: UUID, conversation_id: UUID, new_status: str, actor_user_id: UUID | None):
        conversation = await self._get_for_business(business_id, conversation_id)
        old_status = conversation.status
        if conversation.archived_at is not None and new_status != "open":
            raise ForbiddenException("Archived conversation must be unarchived first")
        if old_status == new_status:
            return conversation

        valid = {
            "open": {"pending", "resolved", "closed", "archived"},
            "pending": {"open", "resolved", "closed", "archived"},
            "resolved": {"open", "closed", "archived"},
            "closed": {"open", "archived"},
            "archived": {"open"},
        }
        if new_status not in valid.get(old_status, set()):
            raise ConflictException(f"Invalid conversation transition {old_status} -> {new_status}")

        conversation.status = new_status
        if new_status == "archived":
            conversation.archived_at = datetime.now(timezone.utc)
        elif old_status == "archived" and new_status == "open":
            conversation.archived_at = None

        self.db.add(
            ConversationStatusEvent(
                conversation_id=conversation.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=actor_user_id,
            )
        )
        self.db.add(
            OutboxEvent(
                business_id=business_id,
                event_type="conversation.status.changed",
                payload_json={
                    "conversation_id": str(conversation.id),
                    "old_status": old_status,
                    "new_status": new_status,
                    "actor_user_id": str(actor_user_id) if actor_user_id else None,
                },
                status="pending",
            )
        )
        await self.audit.write(
            action="conversation.status.changed",
            resource_type="conversation",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user" if actor_user_id else "system",
            actor_id=str(actor_user_id) if actor_user_id else None,
            resource_id=str(conversation.id),
            details={"old_status": old_status, "new_status": new_status},
        )
        await self.db.commit()
        return conversation

    async def close(self, business_id: UUID, conversation_id: UUID, actor_user_id: UUID | None):
        return await self._transition(business_id, conversation_id, "closed", actor_user_id)

    async def reopen(self, business_id: UUID, conversation_id: UUID, actor_user_id: UUID | None):
        return await self._transition(business_id, conversation_id, "open", actor_user_id)

    async def archive(self, business_id: UUID, conversation_id: UUID, actor_user_id: UUID | None):
        return await self._transition(business_id, conversation_id, "archived", actor_user_id)

    async def assign(self, business_id: UUID, conversation_id: UUID, actor_user_id: UUID | None, assigned_user_id: UUID | None, assigned_team_id: UUID | None):
        conversation = await self._get_for_business(business_id, conversation_id)
        if conversation.archived_at is not None:
            raise ForbiddenException("Cannot modify assignment on archived conversation")
        conversation.assigned_user_id = assigned_user_id
        conversation.assigned_team_id = assigned_team_id
        self.db.add(
            ConversationAssignment(
                conversation_id=conversation.id,
                assigned_user_id=assigned_user_id,
                assigned_team_id=assigned_team_id,
                status="active",
            )
        )
        self.db.add(
            OutboxEvent(
                business_id=business_id,
                event_type="conversation.assigned",
                payload_json={
                    "conversation_id": str(conversation.id),
                    "assigned_user_id": str(assigned_user_id) if assigned_user_id else None,
                    "assigned_team_id": str(assigned_team_id) if assigned_team_id else None,
                    "actor_user_id": str(actor_user_id) if actor_user_id else None,
                },
                status="pending",
            )
        )
        await self.audit.write(
            action="conversation.assigned",
            resource_type="conversation",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user" if actor_user_id else "system",
            actor_id=str(actor_user_id) if actor_user_id else None,
            resource_id=str(conversation.id),
            details={
                "assigned_user_id": str(assigned_user_id) if assigned_user_id else None,
                "assigned_team_id": str(assigned_team_id) if assigned_team_id else None,
            },
        )
        await self.db.commit()
        return conversation

    async def record_message_activity(self, business_id: UUID, conversation_id: UUID, actor_user_id: UUID | None = None):
        conversation = await self._get_for_business(business_id, conversation_id)
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.add(
            OutboxEvent(
                business_id=business_id,
                event_type="conversation.activity.recorded",
                payload_json={
                    "conversation_id": str(conversation.id),
                    "actor_user_id": str(actor_user_id) if actor_user_id else None,
                },
                status="pending",
            )
        )
        await self.db.commit()
        return conversation

    async def upsert_sla_policy(
        self,
        business_id: UUID,
        name: str,
        response_minutes: int,
        resolution_minutes: int,
        actor_user_id: UUID | None,
    ) -> SlaPolicy:
        row = await self.db.execute(
            select(SlaPolicy).where(
                SlaPolicy.business_id == business_id,
                SlaPolicy.name == name,
                SlaPolicy.deleted_at.is_(None),
            )
        )
        policy = row.scalar_one_or_none()
        if policy is None:
            policy = SlaPolicy(
                business_id=business_id,
                name=name,
                response_minutes=response_minutes,
                resolution_minutes=resolution_minutes,
            )
            self.db.add(policy)
        else:
            policy.response_minutes = response_minutes
            policy.resolution_minutes = resolution_minutes

        await self.audit.write(
            action="conversation.sla_policy.upserted",
            resource_type="sla_policy",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user" if actor_user_id else "system",
            actor_id=str(actor_user_id) if actor_user_id else None,
            resource_id=str(policy.id) if policy.id else None,
            details={
                "name": name,
                "response_minutes": response_minutes,
                "resolution_minutes": resolution_minutes,
            },
        )
        await self.db.commit()
        await self.db.refresh(policy)
        return policy

    async def apply_sla_policy(
        self,
        business_id: UUID,
        conversation_id: UUID,
        actor_user_id: UUID | None,
        policy_name: str | None = None,
    ) -> Conversation:
        conversation = await self._get_for_business(business_id, conversation_id)
        now = datetime.now(timezone.utc)
        policy_query = select(SlaPolicy).where(SlaPolicy.business_id == business_id, SlaPolicy.deleted_at.is_(None))
        if policy_name:
            policy_query = policy_query.where(SlaPolicy.name == policy_name)
        policy_query = policy_query.order_by(SlaPolicy.updated_at.desc(), SlaPolicy.created_at.desc())
        policy = (await self.db.execute(policy_query.limit(1))).scalar_one_or_none()
        if policy is None:
            raise NotFoundException("SLA policy not found")

        conversation.first_response_due_at = now + timedelta(minutes=policy.response_minutes)
        conversation.resolution_due_at = now + timedelta(minutes=policy.resolution_minutes)
        self.db.add(
            OutboxEvent(
                business_id=business_id,
                event_type="conversation.sla.applied",
                payload_json={
                    "conversation_id": str(conversation.id),
                    "policy_name": policy.name,
                    "first_response_due_at": conversation.first_response_due_at.isoformat(),
                    "resolution_due_at": conversation.resolution_due_at.isoformat(),
                    "actor_user_id": str(actor_user_id) if actor_user_id else None,
                },
                status="pending",
            )
        )
        await self.audit.write(
            action="conversation.sla.applied",
            resource_type="conversation",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user" if actor_user_id else "system",
            actor_id=str(actor_user_id) if actor_user_id else None,
            resource_id=str(conversation.id),
            details={
                "policy_name": policy.name,
                "first_response_due_at": conversation.first_response_due_at.isoformat(),
                "resolution_due_at": conversation.resolution_due_at.isoformat(),
            },
        )
        await self.db.commit()
        return conversation

    async def auto_route_assignment(
        self,
        business_id: UUID,
        conversation_id: UUID,
        actor_user_id: UUID | None,
        strategy: str,
        team_id: UUID | None = None,
        eligible_user_ids: list[UUID] | None = None,
        max_capacity_per_agent: int = 20,
    ) -> tuple[Conversation, int | None]:
        conversation = await self._get_for_business(business_id, conversation_id)
        if conversation.archived_at is not None:
            raise ForbiddenException("Cannot assign archived conversation")

        eligible_user_ids = eligible_user_ids or []
        if eligible_user_ids:
            candidates = eligible_user_ids
        elif team_id:
            rows = await self.db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team_id, TeamMember.deleted_at.is_(None)))
            candidates = [r[0] for r in rows.all()]
        else:
            rows = await self.db.execute(
                select(Agent.user_id).where(
                    Agent.business_id == business_id,
                    Agent.status.in_(["online", "away", "busy"]),
                    Agent.deleted_at.is_(None),
                )
            )
            candidates = [r[0] for r in rows.all()]

        if not candidates:
            raise ConflictException("No eligible agents found")

        load_rows = await self.db.execute(
            select(Conversation.assigned_user_id, func.count(Conversation.id))
            .where(
                Conversation.business_id == business_id,
                Conversation.status.in_(["open", "pending"]),
                Conversation.deleted_at.is_(None),
                Conversation.assigned_user_id.is_not(None),
            )
            .group_by(Conversation.assigned_user_id)
        )
        load_map = {row[0]: int(row[1]) for row in load_rows.all()}

        picked_user: UUID | None = None
        if strategy == "round_robin":
            last_row = await self.db.execute(
                select(ConversationAssignment.assigned_user_id)
                .where(
                    ConversationAssignment.assigned_user_id.in_(candidates),
                    ConversationAssignment.deleted_at.is_(None),
                )
                .order_by(ConversationAssignment.created_at.desc())
                .limit(1)
            )
            last_assigned = last_row.scalar_one_or_none()
            ordered = sorted(candidates, key=lambda x: str(x))
            if last_assigned in ordered:
                idx = ordered.index(last_assigned)
                picked_user = ordered[(idx + 1) % len(ordered)]
            else:
                picked_user = ordered[0]
        elif strategy == "capacity":
            under_capacity = [uid for uid in candidates if load_map.get(uid, 0) < max_capacity_per_agent]
            if not under_capacity:
                raise ConflictException("No eligible agents under capacity")
            picked_user = sorted(under_capacity, key=lambda uid: (load_map.get(uid, 0), str(uid)))[0]
        else:
            picked_user = sorted(candidates, key=lambda uid: (load_map.get(uid, 0), str(uid)))[0]

        assigned_load = load_map.get(picked_user, 0)
        updated = await self.assign(
            business_id=business_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            assigned_user_id=picked_user,
            assigned_team_id=team_id,
        )
        return updated, assigned_load
