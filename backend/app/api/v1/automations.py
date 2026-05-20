from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.models.business_domains import (
    AutomationExecution,
    AutomationExecutionStep,
    AutomationFlow,
    AutomationFlowVersion,
)

router = APIRouter(prefix="/automations", tags=["Automations"])


@router.get("/flows", response_model=list[dict])
async def list_automation_flows(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AutomationFlow).where(
        AutomationFlow.business_id == actor.business.id,
        AutomationFlow.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(AutomationFlow.status == status.strip().lower())
    rows = (await db.execute(stmt.order_by(AutomationFlow.created_at.desc(), AutomationFlow.id.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "status": r.status,
            "workspace_id": str(r.workspace_id) if r.workspace_id else None,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/flows", response_model=dict)
async def create_automation_flow(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise BadRequestException("name is required")
    status = str(payload.get("status") or "active").strip().lower()
    if status not in {"active", "paused", "draft", "disabled"}:
        raise BadRequestException("status must be active/paused/draft/disabled")

    workspace_id = payload.get("workspace_id")
    definition_json = payload.get("definition_json") if isinstance(payload.get("definition_json"), dict) else {}

    flow = AutomationFlow(
        business_id=actor.business.id,
        workspace_id=UUID(str(workspace_id)) if workspace_id else None,
        name=name,
        status=status,
    )
    db.add(flow)
    await db.flush()

    version = AutomationFlowVersion(
        automation_flow_id=flow.id,
        flow_version=1,
        definition_json=definition_json,
        status="draft",
    )
    db.add(version)
    await db.commit()
    return {
        "id": str(flow.id),
        "name": flow.name,
        "status": flow.status,
        "workspace_id": str(flow.workspace_id) if flow.workspace_id else None,
        "initial_version": 1,
    }


@router.get("/flows/{flow_id}", response_model=dict)
async def get_automation_flow(
    flow_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        flow_uuid = UUID(flow_id)
    except ValueError as exc:
        raise BadRequestException("Invalid flow id") from exc

    flow = (
        await db.execute(
            select(AutomationFlow).where(
                AutomationFlow.id == flow_uuid,
                AutomationFlow.business_id == actor.business.id,
                AutomationFlow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not flow:
        raise NotFoundException("Automation flow not found")

    versions = (
        await db.execute(
            select(AutomationFlowVersion)
            .where(
                AutomationFlowVersion.automation_flow_id == flow.id,
                AutomationFlowVersion.deleted_at.is_(None),
            )
            .order_by(AutomationFlowVersion.flow_version.desc(), AutomationFlowVersion.id.desc())
            .limit(20)
        )
    ).scalars().all()
    return {
        "id": str(flow.id),
        "name": flow.name,
        "status": flow.status,
        "workspace_id": str(flow.workspace_id) if flow.workspace_id else None,
        "versions": [
            {
                "id": str(v.id),
                "flow_version": int(v.flow_version),
                "status": v.status,
                "definition_json": v.definition_json or {},
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
        "created_at": flow.created_at.isoformat(),
        "updated_at": flow.updated_at.isoformat(),
    }


@router.patch("/flows/{flow_id}/status", response_model=dict)
async def update_automation_flow_status(
    flow_id: str,
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        flow_uuid = UUID(flow_id)
    except ValueError as exc:
        raise BadRequestException("Invalid flow id") from exc
    next_status = str(payload.get("status") or "").strip().lower()
    if next_status not in {"active", "paused", "draft", "disabled"}:
        raise BadRequestException("status must be active/paused/draft/disabled")

    row = (
        await db.execute(
            select(AutomationFlow).where(
                AutomationFlow.id == flow_uuid,
                AutomationFlow.business_id == actor.business.id,
                AutomationFlow.deleted_at.is_(None),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("Automation flow not found")
    row.status = next_status
    await db.commit()
    return {"id": str(row.id), "status": row.status, "updated_at": row.updated_at.isoformat()}


@router.get("/executions", response_model=list[dict])
async def list_automation_executions(
    flow_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AutomationExecution, AutomationFlow)
        .join(AutomationFlow, AutomationFlow.id == AutomationExecution.automation_flow_id)
        .where(
            AutomationFlow.business_id == actor.business.id,
            AutomationFlow.deleted_at.is_(None),
            AutomationExecution.deleted_at.is_(None),
        )
    )
    if flow_id:
        try:
            flow_uuid = UUID(flow_id)
        except ValueError as exc:
            raise BadRequestException("Invalid flow_id") from exc
        stmt = stmt.where(AutomationExecution.automation_flow_id == flow_uuid)
    if status:
        stmt = stmt.where(AutomationExecution.status == status.strip().lower())
    rows = (await db.execute(stmt.order_by(AutomationExecution.created_at.desc(), AutomationExecution.id.desc()).limit(limit))).all()
    return [
        {
            "id": str(exe.id),
            "automation_flow_id": str(exe.automation_flow_id),
            "flow_name": flow.name,
            "flow_version": int(exe.flow_version),
            "status": exe.status,
            "context_json": exe.context_json or {},
            "created_at": exe.created_at.isoformat(),
            "updated_at": exe.updated_at.isoformat(),
        }
        for exe, flow in rows
    ]


@router.get("/executions/{execution_id}/steps", response_model=list[dict])
async def list_automation_execution_steps(
    execution_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        execution_uuid = UUID(execution_id)
    except ValueError as exc:
        raise BadRequestException("Invalid execution id") from exc

    execution = (
        await db.execute(
            select(AutomationExecution, AutomationFlow)
            .join(AutomationFlow, AutomationFlow.id == AutomationExecution.automation_flow_id)
            .where(
                AutomationExecution.id == execution_uuid,
                AutomationExecution.deleted_at.is_(None),
                AutomationFlow.business_id == actor.business.id,
                AutomationFlow.deleted_at.is_(None),
            )
        )
    ).first()
    if not execution:
        raise NotFoundException("Automation execution not found")

    rows = (
        await db.execute(
            select(AutomationExecutionStep).where(
                AutomationExecutionStep.automation_execution_id == execution_uuid,
                AutomationExecutionStep.deleted_at.is_(None),
            ).order_by(AutomationExecutionStep.created_at.asc(), AutomationExecutionStep.id.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "automation_execution_id": str(r.automation_execution_id),
            "step_key": r.step_key,
            "status": r.status,
            "details_json": r.details_json or {},
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]
