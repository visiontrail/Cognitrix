"""Super-admin REST surface for managing Claude Agent SDK skill bundles.

All routes are gated by ``require_permission("skills:admin")``, which is granted
only to the ``superadmin`` role. The router is mounted from ``main.py`` only
when ``AGENT_SKILLS_ENABLED`` is true.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from .agent_skills import (
    AgentSkillRecord,
    SkillNotFoundError,
    get_skill_registry,
)
from .agent_skills.agents import NAMED_AGENTS
from .agent_skills.installer import install_skill_bundle
from .agent_skills.registry import VALID_STATUSES
from .audit import get_audit_logger
from .auth import AuthIdentity, require_permission
from .config import get_settings
from .agent_skills.validator import SkillBundleError
from .agent_skills.manifest import ManifestError

logger = logging.getLogger("cognitrix.admin_skills")

# Alias for legacy callers (and the existing test suite); the canonical source
# is ``agent_skills.agents.NAMED_AGENTS``.
KNOWN_AGENT_NAMES: tuple[str, ...] = NAMED_AGENTS


router = APIRouter(prefix="/admin/skills", tags=["admin-skills"])


class SkillStatusUpdate(BaseModel):
    status: str = Field(..., description="One of: enabled, disabled")


class SkillAssignmentRequest(BaseModel):
    agent_name: str = Field(..., min_length=1)


def _serialize_skill(record: AgentSkillRecord, *, assignments: list[str]) -> dict[str, Any]:
    payload = record.to_dict()
    payload["assignments"] = list(assignments)
    return payload


def _record_or_404(skill_id: str) -> AgentSkillRecord:
    try:
        return get_skill_registry().get(skill_id)
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "skill_not_found", "message": f"skill {skill_id} not found"},
        ) from exc


def _list_assignment_names(skill_id: str) -> list[str]:
    return [a.agent_name for a in get_skill_registry().list_assignments_for_skill(skill_id)]


def _audit(
    *,
    action: str,
    status: str,
    identity: AuthIdentity,
    detail: dict[str, Any] | None = None,
    severity: str = "INFO",
) -> None:
    get_audit_logger().log(
        event_type="agent_skills",
        action=action,
        status=status,
        severity=severity,
        user_id=identity.user_id,
        project_id=identity.project_id,
        resource="admin.skills",
        detail=detail or {},
    )


def _invalidate_loader_cache() -> None:
    """Bust the runtime loader's TTL cache after any write."""
    try:
        from .agent_skills.loader import invalidate_skill_loader_cache

        invalidate_skill_loader_cache()
    except ImportError:
        # Loader is added in section 7; missing module is acceptable while the
        # admin API is in use before runtime integration ships.
        pass


@router.post("", status_code=201)
async def upload_skill(
    file: UploadFile = File(...),
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> dict[str, Any]:
    settings = get_settings()
    max_bytes = settings.agent_skills_max_upload_mb * 1024 * 1024
    raw = await file.read()
    if not raw:
        _audit(
            action="skill_upload_rejected",
            status="denied",
            severity="ALERT",
            identity=identity,
            detail={"reason": "empty_upload", "filename": file.filename or ""},
        )
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_upload", "message": "uploaded file is empty"},
        )

    try:
        result = install_skill_bundle(
            zip_bytes=raw,
            max_size_bytes=max_bytes,
            skills_dir=settings.resolved_agent_skills_dir,
            uploaded_by=identity.user_id,
        )
    except SkillBundleError as exc:
        status_code = 413 if exc.code == "bundle_too_large" else 400
        _audit(
            action="skill_upload_rejected",
            status="denied",
            severity="ALERT",
            identity=identity,
            detail={"reason": exc.code, "filename": file.filename or ""},
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ManifestError as exc:
        _audit(
            action="skill_upload_rejected",
            status="denied",
            severity="ALERT",
            identity=identity,
            detail={"reason": exc.code, "filename": file.filename or ""},
        )
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    _invalidate_loader_cache()
    _audit(
        action="skill_upload",
        status="success",
        identity=identity,
        detail={
            "skill_id": result.skill_id,
            "name": result.manifest.name,
            "version": result.manifest.version,
            "sha256": result.record.sha256,
        },
    )
    return _serialize_skill(result.record, assignments=[])


@router.get("")
async def list_skills(
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> dict[str, Any]:
    _ = identity
    registry = get_skill_registry()
    skills = registry.list()
    items = [
        _serialize_skill(record, assignments=_list_assignment_names(record.id))
        for record in skills
    ]
    return {"count": len(items), "skills": items}


@router.get("/agents/{agent_name}")
async def list_skills_for_agent(
    agent_name: str,
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> dict[str, Any]:
    _ = identity
    normalized = agent_name.strip()
    if normalized not in KNOWN_AGENT_NAMES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_agent",
                "message": f"agent_name must be one of {list(KNOWN_AGENT_NAMES)}",
            },
        )
    registry = get_skill_registry()
    assignments = registry.list_assignments_for_agent(normalized)
    skills: list[dict[str, Any]] = []
    for assignment in assignments:
        try:
            record = registry.get(assignment.skill_id)
        except SkillNotFoundError:
            continue
        skills.append(
            {
                **record.to_dict(),
                "assigned_at": assignment.assigned_at,
                "assigned_by": assignment.assigned_by,
            }
        )
    return {"agent_name": normalized, "count": len(skills), "skills": skills}


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> dict[str, Any]:
    _ = identity
    record = _record_or_404(skill_id)
    return _serialize_skill(record, assignments=_list_assignment_names(skill_id))


@router.patch("/{skill_id}")
async def update_skill_status(
    skill_id: str,
    payload: SkillStatusUpdate,
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> dict[str, Any]:
    normalized = payload.status.strip().lower()
    if normalized not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_status",
                "message": f"status must be one of {sorted(VALID_STATUSES)}",
            },
        )
    registry = get_skill_registry()
    try:
        record = registry.set_status(skill_id, normalized)
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "skill_not_found", "message": f"skill {skill_id} not found"},
        ) from exc

    _invalidate_loader_cache()
    audit_action = "skill_enable" if normalized == "enabled" else "skill_disable"
    _audit(
        action=audit_action,
        status="success",
        identity=identity,
        detail={"skill_id": skill_id, "name": record.name},
    )
    return _serialize_skill(record, assignments=_list_assignment_names(skill_id))


@router.delete("/{skill_id}", status_code=204, response_class=Response)
async def delete_skill(
    skill_id: str,
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> Response:
    record = _record_or_404(skill_id)
    bundle_dir = Path(record.bundle_dir)
    try:
        get_skill_registry().delete(skill_id)
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "skill_not_found", "message": f"skill {skill_id} not found"},
        ) from exc

    # Best-effort filesystem cleanup; missing dir is fine (e.g. manual cleanup).
    if bundle_dir.exists():
        try:
            shutil.rmtree(bundle_dir)
        except OSError as exc:
            logger.warning(
                "skill_bundle_cleanup_failed skill_id=%s bundle_dir=%s error=%s",
                skill_id,
                bundle_dir,
                exc,
            )

    _invalidate_loader_cache()
    _audit(
        action="skill_delete",
        status="success",
        identity=identity,
        detail={"skill_id": skill_id, "name": record.name},
    )
    return Response(status_code=204)


@router.post("/{skill_id}/assignments", status_code=201)
async def assign_skill(
    skill_id: str,
    payload: SkillAssignmentRequest,
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> dict[str, Any]:
    agent_name = payload.agent_name.strip()
    if agent_name not in KNOWN_AGENT_NAMES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_agent",
                "message": f"agent_name must be one of {list(KNOWN_AGENT_NAMES)}",
            },
        )
    try:
        assignment = get_skill_registry().assign(
            skill_id=skill_id,
            agent_name=agent_name,
            assigned_by=identity.user_id,
        )
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "skill_not_found", "message": f"skill {skill_id} not found"},
        ) from exc

    _invalidate_loader_cache()
    _audit(
        action="skill_assign",
        status="success",
        identity=identity,
        detail={"skill_id": skill_id, "agent_name": agent_name},
    )
    return {
        "skill_id": assignment.skill_id,
        "agent_name": assignment.agent_name,
        "assigned_by": assignment.assigned_by,
        "assigned_at": assignment.assigned_at,
    }


@router.delete(
    "/{skill_id}/assignments/{agent_name}",
    status_code=204,
    response_class=Response,
)
async def unassign_skill(
    skill_id: str,
    agent_name: str,
    identity: AuthIdentity = Depends(require_permission("skills:admin")),
) -> Response:
    normalized = agent_name.strip()
    if normalized not in KNOWN_AGENT_NAMES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_agent",
                "message": f"agent_name must be one of {list(KNOWN_AGENT_NAMES)}",
            },
        )
    # Ensure the skill exists so we return 404 instead of a silent no-op for a
    # missing id (which would be indistinguishable from a missing assignment).
    _record_or_404(skill_id)
    removed = get_skill_registry().unassign(skill_id=skill_id, agent_name=normalized)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "assignment_not_found",
                "message": f"no assignment of {skill_id} to {normalized}",
            },
        )

    _invalidate_loader_cache()
    _audit(
        action="skill_unassign",
        status="success",
        identity=identity,
        detail={"skill_id": skill_id, "agent_name": normalized},
    )
    return Response(status_code=204)
