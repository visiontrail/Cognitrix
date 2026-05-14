from __future__ import annotations

from dataclasses import dataclass

INGESTION_ACTIVE_STATUSES = frozenset(
    {
        "uploaded",
        "planning",
        "awaiting_catalog_setup",
        "awaiting_user_approval",
        "approved",
        "executing",
    }
)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        return {"route": self.route, "reason": self.reason}


def select_agent_route(
    *,
    message: str | None,
    has_files: bool,
    ingestion_job_status: str | None,
) -> RouteDecision:
    """Choose between the write-ingestion agent and the query agent.

    Routing is intentionally minimal: only physical signals (file attachments,
    an active ingestion lifecycle) force the write route. Free-form intent is
    deferred to the query agent, which can ask follow-up questions or guide the
    user to the upload affordance when it detects a write goal.
    """
    _ = message  # intent is deliberately not parsed; the query agent handles it

    if has_files:
        return RouteDecision(route="write_ingestion", reason="request_has_attachments")

    if (ingestion_job_status or "").strip() in INGESTION_ACTIVE_STATUSES:
        return RouteDecision(route="write_ingestion", reason="ingestion_lifecycle_active")

    return RouteDecision(route="query", reason="default_query_route")
