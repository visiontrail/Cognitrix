#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Cognitrix smoke flow")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--web-base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    # Legacy service-token auth
    parser.add_argument("--user-id", default="smoke-hr")
    parser.add_argument("--project-id", default="smoke-project")
    parser.add_argument("--role", default="hr")
    # New email/password auth (used when --email is provided)
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="SmokePwd123!")
    # Section 12 — exercise the vendored xlsx skill path end-to-end. Requires
    # AGENT_SKILLS_ENABLED=true on the API and that the bootstrap has
    # successfully installed and assigned anthropic/xlsx to WriteIngestionAgent.
    parser.add_argument(
        "--with-skills",
        action="store_true",
        help="After login, verify that the vendored xlsx skill is installed "
        "and assigned to WriteIngestionAgent via /admin/skills (requires the "
        "smoke user to be a superadmin).",
    )
    return parser.parse_args()


def wait_for_http_ok(client: httpx.Client, url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error = "unknown"
    while time.time() < deadline:
        try:
            response = client.get(url)
            if response.status_code == 200:
                return
            last_error = f"status={response.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"timeout waiting for {url}: {last_error}")


def parse_sse(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for frame in raw.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        event = "message"
        data_lines: list[str] = []
        event_id: str | None = None

        for line in frame.splitlines():
            if line.startswith("id:"):
                event_id = line.split(":", 1)[1].strip()
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                continue
            if line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())

        if not data_lines:
            continue

        merged = "\n".join(data_lines)
        payload: Any
        try:
            payload = json.loads(merged)
        except json.JSONDecodeError:
            payload = {"raw": merged}
        events.append({"id": event_id, "event": event, "data": payload})
    return events


def build_excel_files(workdir: Path) -> list[Path]:
    first = pd.DataFrame(
        [
            {
                "employee_id": "E-1001",
                "employee_name": "Alice",
                "department": "HR",
                "status": "active",
                "salary": 12000,
                "region": "CN-East",
            },
            {
                "employee_id": "E-1002",
                "employee_name": "Bob",
                "department": "PM",
                "status": "active",
                "salary": 13500,
                "region": "CN-East",
            },
        ]
    )
    second = pd.DataFrame(
        [
            {
                "Name": "Cindy",
                "Employee ID": "E-1003",
                "Dept": "HR",
                "State": "inactive",
                "Project": "Nebula",
                "Score": 82,
            },
            {
                "Name": "David",
                "Employee ID": "E-1004",
                "Dept": "PM",
                "State": "active",
                "Project": "Galaxy",
                "Score": 91,
            },
        ]
    )

    first_file = workdir / "employees_a.xlsx"
    second_file = workdir / "employees_b.xlsx"
    first.to_excel(first_file, index=False)
    second.to_excel(second_file, index=False)
    return [first_file, second_file]


def verify_xlsx_skill_bootstrap(
    client: httpx.Client,
    api_base_url: str,
    auth_headers: dict[str, str],
) -> None:
    """Assert the vendored Anthropic xlsx skill is installed and assigned.

    Hits ``GET /admin/skills`` (requires the calling user to be a superadmin)
    and confirms there is a skill named ``anthropic/xlsx`` in status
    ``enabled`` with ``WriteIngestionAgent`` in its assignments. Raises with a
    descriptive error otherwise so the smoke flow exits non-zero.
    """
    response = client.get(f"{api_base_url}/admin/skills", headers=auth_headers)
    if response.status_code == 403:
        raise RuntimeError(
            "/admin/skills returned 403 — smoke user is not a superadmin. "
            "Set AUTH_BOOTSTRAP_SUPERADMIN_EMAIL on the API to that user."
        )
    if response.status_code == 404:
        raise RuntimeError(
            "/admin/skills returned 404 — AGENT_SKILLS_ENABLED is likely off."
        )
    response.raise_for_status()

    payload = response.json()
    skills = payload.get("skills", [])
    xlsx = next((s for s in skills if s.get("name") == "anthropic/xlsx"), None)
    if xlsx is None:
        raise RuntimeError(
            "anthropic/xlsx skill not present in /admin/skills — vendor it "
            "into apps/api/vendor/skills/ and update VERSIONS.md sha256."
        )
    if xlsx.get("status") != "enabled":
        raise RuntimeError(
            f"anthropic/xlsx is present but status={xlsx.get('status')!r}; expected enabled."
        )
    if "WriteIngestionAgent" not in xlsx.get("assignments", []):
        raise RuntimeError(
            "anthropic/xlsx is not assigned to WriteIngestionAgent. "
            "Re-run bootstrap or assign manually via the admin UI."
        )
    print(
        "[smoke][with-skills] anthropic/xlsx verified — version=",
        xlsx.get("version") or "?",
        " sha256=",
        (xlsx.get("sha256") or "")[:12],
        sep="",
    )


def main() -> int:
    args = parse_args()

    api_base_url = args.api_base_url.rstrip("/")
    web_base_url = args.web_base_url.rstrip("/")

    with httpx.Client(timeout=40.0) as client:
        wait_for_http_ok(client, f"{api_base_url}/healthz", args.timeout_seconds)
        wait_for_http_ok(client, web_base_url, args.timeout_seconds)

        if args.email:
            # New email+password flow
            smoke_email = args.email
            smoke_password = args.password
            # Try register first (idempotent: if exists, login)
            reg_resp = client.post(f"{api_base_url}/auth/register", json={
                "email": smoke_email,
                "password": smoke_password,
                "display_name": "Smoke User",
                "job_id": 1,
            })
            if reg_resp.status_code == 409:
                # Already registered, login
                login_response = client.post(f"{api_base_url}/auth/email-login", json={
                    "email": smoke_email,
                    "password": smoke_password,
                })
                login_response.raise_for_status()
                token = login_response.json().get("access_token")
            elif reg_resp.status_code == 200:
                token = reg_resp.json().get("access_token")
            else:
                reg_resp.raise_for_status()
                token = None
        else:
            # Legacy service-token flow
            login_response = client.post(
                f"{api_base_url}/auth/login",
                json={
                    "user_id": args.user_id,
                    "project_id": args.project_id,
                    "role": args.role,
                    "department": "HR",
                    "clearance": 2,
                },
            )
            login_response.raise_for_status()
            token = login_response.json().get("access_token")
        if not token:
            raise RuntimeError("missing access_token")

        auth_headers = {"Authorization": f"Bearer {token}"}

        if args.with_skills:
            verify_xlsx_skill_bootstrap(client, api_base_url, auth_headers)

        workspace_response = client.post(
            f"{api_base_url}/workspaces",
            headers=auth_headers,
            json={"name": f"Smoke Workspace {int(time.time())}"},
        )
        workspace_response.raise_for_status()
        workspace_id = str(workspace_response.json().get("workspace_id", ""))
        if not workspace_id:
            raise RuntimeError("workspace response missing workspace_id")

        with tempfile.TemporaryDirectory(prefix="cognitrix-smoke-") as tmp_dir:
            file_path = build_excel_files(Path(tmp_dir))[0]
            upload_response = client.post(
                f"{api_base_url}/ingestion/uploads",
                headers=auth_headers,
                data={"workspace_id": workspace_id},
                files=[("files", (file_path.name, file_path.read_bytes(), XLSX_MIME))],
            )
            upload_response.raise_for_status()
            upload_payload = upload_response.json()

        job_id = str(upload_payload.get("job_id", ""))
        if not job_id:
            raise RuntimeError("upload response missing job_id")

        plan_response = client.post(
            f"{api_base_url}/ingestion/plan",
            headers=auth_headers,
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "conversation_id": "smoke-conversation",
                "message": "ingest smoke workbook",
            },
        )
        plan_response.raise_for_status()
        plan_payload = plan_response.json()
        if plan_payload.get("status") == "awaiting_catalog_setup":
            setup_response = client.post(
                f"{api_base_url}/ingestion/setup/confirm",
                headers=auth_headers,
                json={
                    "workspace_id": workspace_id,
                    "job_id": job_id,
                    "conversation_id": "smoke-conversation",
                    "message": "confirm smoke catalog setup",
                    "setup": plan_payload["suggested_catalog_seed"],
                },
            )
            setup_response.raise_for_status()
            plan_payload = setup_response.json()

        if plan_payload.get("status") != "awaiting_user_approval":
            raise RuntimeError(f"unexpected ingestion plan status: {plan_payload}")

        proposal = plan_payload["proposal"]
        proposal_id = str(plan_payload.get("proposal_id", ""))
        approved_action = str(proposal.get("recommended_action", "new_table"))
        approve_response = client.post(
            f"{api_base_url}/ingestion/approve",
            headers=auth_headers,
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": proposal_id,
                "approved_action": approved_action,
                "user_overrides": {"time_grain": proposal.get("time_grain", "none")},
            },
        )
        approve_response.raise_for_status()

        execute_response = client.post(
            f"{api_base_url}/ingestion/execute",
            headers=auth_headers,
            json={"workspace_id": workspace_id, "job_id": job_id, "proposal_id": proposal_id},
        )
        execute_response.raise_for_status()
        receipt = execute_response.json()["receipt"]
        dataset_table = str(receipt.get("target_table", ""))
        if not dataset_table:
            raise RuntimeError("ingestion receipt missing target_table")

        semantic_response = client.post(
            f"{api_base_url}/semantic/query",
            headers=auth_headers,
            json={
                "user_id": args.user_id,
                "project_id": args.project_id,
                "workspace_id": workspace_id,
                "dataset_table": dataset_table,
                "metric": "headcount_total",
                "group_by": ["department"],
                "role": args.role,
                "department": "HR",
                "clearance": 2,
            },
        )
        semantic_response.raise_for_status()
        semantic_payload = semantic_response.json()
        if int(semantic_payload.get("row_count", 0)) <= 0:
            raise RuntimeError("semantic query returned no rows")

        stream_response = client.post(
            f"{api_base_url}/chat/stream",
            headers=auth_headers,
            json={
                "user_id": args.user_id,
                "project_id": args.project_id,
                "workspace_id": workspace_id,
                "dataset_table": dataset_table,
                "message": "headcount by department",
                "conversation_id": "smoke-conversation",
                "role": args.role,
                "department": "HR",
                "clearance": 2,
            },
        )
        stream_response.raise_for_status()

        stream_events = parse_sse(stream_response.text)
        if not stream_events:
            raise RuntimeError("chat stream produced no events")

        final_events = [event for event in stream_events if event["event"] == "final"]
        spec_events = [event for event in stream_events if event["event"] == "spec"]
        if not final_events or not spec_events:
            raise RuntimeError("chat stream missing spec/final events")

        final_payload = final_events[-1]["data"]
        if not isinstance(final_payload, dict) or final_payload.get("status") != "completed":
            raise RuntimeError(f"chat stream final status is not completed: {final_payload}")

        spec_payload = spec_events[-1]["data"]
        if not isinstance(spec_payload, dict) or not isinstance(spec_payload.get("spec"), dict):
            raise RuntimeError("chat stream spec payload invalid")

        save_response = client.post(
            f"{api_base_url}/views",
            headers=auth_headers,
            json={
                "user_id": args.user_id,
                "project_id": args.project_id,
                "workspace_id": workspace_id,
                "dataset_table": dataset_table,
                "role": args.role,
                "department": "HR",
                "clearance": 2,
                "title": "Smoke View",
                "conversation_id": "smoke-conversation",
                "ai_state": {
                    "messages": [
                        {"id": "smoke-user", "role": "user", "text": "headcount by department"},
                        {
                            "id": "smoke-assistant",
                            "role": "assistant",
                            "text": str(final_payload.get("text", "")),
                        },
                    ],
                    "active_spec": spec_payload.get("spec"),
                    "dataset_table": dataset_table,
                },
            },
        )
        save_response.raise_for_status()
        save_payload = save_response.json()
        view_id = str(save_payload.get("view_id", ""))
        if not view_id:
            raise RuntimeError("save view response missing view_id")

        share_response = client.get(f"{api_base_url}/share/{view_id}", headers=auth_headers)
        share_response.raise_for_status()
        share_payload = share_response.json()
        if str(share_payload.get("view_id", "")) != view_id:
            raise RuntimeError("share payload view_id mismatch")

        publish_rows = semantic_payload.get("rows")
        if not isinstance(publish_rows, list) or not publish_rows:
            publish_rows = [{"department": "HR", "headcount": semantic_payload.get("row_count", 1)}]

        publish_response = client.post(
            f"{api_base_url}/workspaces/{workspace_id}/publish",
            headers=auth_headers,
            json={
                "layout": {
                    "grid": {"columns": 2, "rows": [{"id": "row-1", "height": 320}]},
                    "zones": [
                        {
                            "id": "zone-1",
                            "nodeId": "node-smoke-chart",
                            "chartId": "smoke-chart",
                            "column": 0,
                            "row": 0,
                            "colSpan": 1,
                            "rowSpan": 1,
                        }
                    ],
                },
                "sidebar": [{"id": "overview", "label": "Overview", "anchorRowId": "row-1", "children": []}],
                "charts": [
                    {
                        "chart_id": "smoke-chart",
                        "title": "Smoke Headcount",
                        "chart_type": "bar",
                        "spec": spec_payload.get("spec") or {"chart_type": "bar", "title": "Smoke Headcount"},
                        "rows": publish_rows,
                    }
                ],
            },
        )
        publish_response.raise_for_status()
        published_page_id = str(publish_response.json().get("published_page_id", ""))
        if not published_page_id:
            raise RuntimeError("publish response missing published_page_id")

        portal_manifest_response = client.get(f"{api_base_url}/portal/pages/{published_page_id}/manifest")
        portal_manifest_response.raise_for_status()

        portal_chat_response = client.post(
            f"{api_base_url}/portal/pages/{published_page_id}/chat",
            json={"message": "summarize the smoke chart", "chart_id": "smoke-chart"},
        )
        portal_chat_response.raise_for_status()
        portal_events = parse_sse(portal_chat_response.text)
        if not any(event["event"] == "final" for event in portal_events):
            raise RuntimeError("portal chat stream missing final event")

        summary = {
            "job_id": job_id,
            "workspace_id": workspace_id,
            "dataset_table": dataset_table,
            "semantic_rows": semantic_payload.get("row_count", 0),
            "view_id": view_id,
            "share_path": share_payload.get("share_path"),
            "published_page_id": published_page_id,
            "stream_events": len(stream_events),
            "portal_stream_events": len(portal_events),
        }
        print(json.dumps(summary, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
