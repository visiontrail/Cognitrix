from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

MAX_SAMPLE_ROWS = 8


def inspect_nonstructured_workbook(
    *,
    workbook_bytes: bytes | None = None,
    workbook_path: Path | None = None,
) -> dict[str, Any] | None:
    """Detect human-readable matrix workbooks and return structured candidates.

    The first supported pattern is a project resource allocation matrix:
    rows near the top describe projects, the left columns describe people, and
    the project columns contain free-text assignment cells.  The analysis-ready
    primary table is a denormalized long fact table, one row per non-empty
    person/project assignment.
    """

    if workbook_bytes is None and workbook_path is None:
        raise ValueError("workbook_bytes or workbook_path is required")

    workbook_source: BytesIO | Path
    if workbook_bytes is not None:
        workbook_source = BytesIO(workbook_bytes)
    else:
        workbook_source = Path(workbook_path or "")

    try:
        workbook = load_workbook(workbook_source, data_only=True, read_only=False)
    except Exception:
        return None

    best: dict[str, Any] | None = None
    for worksheet in workbook.worksheets:
        candidate = _inspect_project_assignment_matrix(worksheet)
        if candidate is None:
            continue
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate
    return best


def load_primary_structured_dataframe(upload_path: Path) -> pd.DataFrame | None:
    candidate = inspect_nonstructured_workbook(workbook_path=upload_path)
    if not candidate:
        return None
    primary = candidate.get("primary_table")
    if not isinstance(primary, dict):
        return None
    rows = primary.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    return pd.DataFrame(rows)


def _inspect_project_assignment_matrix(worksheet: Worksheet) -> dict[str, Any] | None:
    merged_values = _build_merged_value_lookup(worksheet)
    value = lambda row, col: _cell_text(worksheet, row, col, merged_values)

    header = _find_people_header_row(worksheet, value)
    if header is None:
        return None

    team_col = header["team_col"]
    role_col = header["role_col"]
    name_col = header["name_col"]
    main_work_col = header.get("main_work_col")
    project_start_col = max(team_col, role_col, name_col) + 1
    project_end_col = (main_work_col - 1) if main_work_col else worksheet.max_column

    projects = _extract_projects(
        worksheet=worksheet,
        value=value,
        header_row=header["row"],
        project_start_col=project_start_col,
        project_end_col=project_end_col,
    )
    if len(projects) < 2:
        return None

    people, assignments = _extract_people_and_assignments(
        worksheet=worksheet,
        value=value,
        header_row=header["row"],
        team_col=team_col,
        role_col=role_col,
        name_col=name_col,
        main_work_col=main_work_col,
        projects=projects,
    )
    if len(assignments) < 3:
        return None

    project_rows = [{key: item[key] for key in item if key != "_column"} for item in projects]
    people_rows = list(people.values())

    primary_columns = [
        "source_sheet",
        "source_cell",
        "team",
        "role",
        "person_name",
        "project_year",
        "project_name",
        "project_stage",
        "project_manager",
        "project_intro",
        "project_milestone",
        "assignment_text",
        "main_work_content",
    ]

    return {
        "kind": "project_assignment_matrix",
        "confidence": 0.92,
        "sheet_name": worksheet.title,
        "detection_reasons": [
            "Detected left-side people columns: team, role, name",
            "Detected horizontal project metadata rows above the assignment matrix",
            "Expanded non-empty person/project intersection cells into long fact rows",
            "Merged cells were resolved by inheriting their top-left value",
        ],
        "stats": {
            "project_count": len(project_rows),
            "person_count": len(people_rows),
            "assignment_count": len(assignments),
            "merged_range_count": len(worksheet.merged_cells.ranges),
        },
        "recommended_catalog_seed": {
            "business_type": "project_progress",
            "table_name": "project_assignments",
            "human_label": "项目人员投入分配",
            "write_mode": "new_table",
            "time_grain": "none",
            "primary_keys": ["source_cell"],
            "match_columns": ["source_cell"],
            "is_active_target": True,
            "description": (
                "Structured from a human-readable project assignment matrix. "
                "One row represents one non-empty person/project assignment cell, "
                "with project metadata denormalized for BI analysis."
            ),
        },
        "candidate_tables": [
            {
                "table_name": "projects",
                "label": "项目维表",
                "row_count": len(project_rows),
                "columns": [
                    "project_key",
                    "project_year",
                    "project_name",
                    "project_stage",
                    "project_manager",
                    "project_intro",
                    "project_milestone",
                ],
                "sample_rows": project_rows[:MAX_SAMPLE_ROWS],
            },
            {
                "table_name": "people",
                "label": "人员维表",
                "row_count": len(people_rows),
                "columns": ["person_key", "team", "role", "person_name", "main_work_content"],
                "sample_rows": people_rows[:MAX_SAMPLE_ROWS],
            },
            {
                "table_name": "project_assignments",
                "label": "项目人员投入分配事实表",
                "row_count": len(assignments),
                "columns": primary_columns,
                "sample_rows": assignments[:MAX_SAMPLE_ROWS],
            },
        ],
        "primary_table": {
            "table_name": "project_assignments",
            "columns": primary_columns,
            "rows": assignments,
            "sample_rows": assignments[:MAX_SAMPLE_ROWS],
        },
    }


def _build_merged_value_lookup(worksheet: Worksheet) -> dict[tuple[int, int], Any]:
    values: dict[tuple[int, int], Any] = {}
    for merged_range in worksheet.merged_cells.ranges:
        top_left = worksheet.cell(merged_range.min_row, merged_range.min_col).value
        for row in range(merged_range.min_row, merged_range.max_row + 1):
            for col in range(merged_range.min_col, merged_range.max_col + 1):
                values[(row, col)] = top_left
    return values


def _cell_text(
    worksheet: Worksheet,
    row: int,
    col: int,
    merged_values: dict[tuple[int, int], Any],
) -> str:
    raw = worksheet.cell(row, col).value
    if raw is None:
        raw = merged_values.get((row, col))
    if raw is None:
        return ""
    return _normalize_text(raw)


def _normalize_text(value: Any) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _find_people_header_row(
    worksheet: Worksheet,
    value: Any,
) -> dict[str, int] | None:
    for row in range(1, min(worksheet.max_row, 20) + 1):
        labels = {col: value(row, col) for col in range(1, worksheet.max_column + 1)}
        team_col = _find_col(labels, ("团队", "部门", "组"))
        role_col = _find_col(labels, ("岗位名称", "岗位", "角色"))
        name_col = _find_col(labels, ("姓名", "人员", "成员"))
        if team_col and role_col and name_col:
            result = {
                "row": row,
                "team_col": team_col,
                "role_col": role_col,
                "name_col": name_col,
            }
            main_work_col = _find_col(labels, ("所负责主要工作内容", "主要工作内容", "负责内容"))
            if not main_work_col:
                main_work_col = _find_col_above_header(
                    worksheet,
                    value,
                    header_row=row,
                    needles=("所负责主要工作内容", "主要工作内容", "负责内容"),
                )
            if main_work_col:
                result["main_work_col"] = main_work_col
            return result
    return None


def _find_col(labels: dict[int, str], needles: tuple[str, ...]) -> int | None:
    for col, label in labels.items():
        compact = label.replace(" ", "")
        if any(needle in compact for needle in needles):
            return col
    return None


def _find_col_above_header(
    worksheet: Worksheet,
    value: Any,
    *,
    header_row: int,
    needles: tuple[str, ...],
) -> int | None:
    for row in range(1, header_row):
        labels = {col: value(row, col) for col in range(1, worksheet.max_column + 1)}
        found = _find_col(labels, needles)
        if found:
            return found
    return None


def _extract_projects(
    *,
    worksheet: Worksheet,
    value: Any,
    header_row: int,
    project_start_col: int,
    project_end_col: int,
) -> list[dict[str, Any]]:
    year_row = max(1, header_row - 6)
    name_row = max(1, header_row - 5)
    stage_row = max(1, header_row - 4)
    manager_row = max(1, header_row - 3)
    intro_row = max(1, header_row - 2)
    milestone_row = max(1, header_row - 1)

    projects: list[dict[str, Any]] = []
    for col in range(project_start_col, project_end_col + 1):
        project_name = value(name_row, col)
        if not project_name:
            continue
        projects.append(
            {
                "_column": col,
                "project_key": f"p{len(projects) + 1:03d}",
                "project_year": value(year_row, col),
                "project_name": project_name,
                "project_stage": value(stage_row, col),
                "project_manager": value(manager_row, col),
                "project_intro": value(intro_row, col),
                "project_milestone": value(milestone_row, col),
            }
        )
    return projects


def _extract_people_and_assignments(
    *,
    worksheet: Worksheet,
    value: Any,
    header_row: int,
    team_col: int,
    role_col: int,
    name_col: int,
    main_work_col: int | None,
    projects: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    people: dict[str, dict[str, Any]] = {}
    assignments: list[dict[str, Any]] = []

    for row in range(header_row + 1, worksheet.max_row + 1):
        person_name = value(row, name_col)
        if not person_name:
            continue
        team = value(row, team_col)
        role = value(row, role_col)
        main_work = value(row, main_work_col) if main_work_col else ""
        person_key = _person_key(team=team, role=role, person_name=person_name)
        people.setdefault(
            person_key,
            {
                "person_key": person_key,
                "team": team,
                "role": role,
                "person_name": person_name,
                "main_work_content": main_work,
            },
        )

        for project in projects:
            col = int(project["_column"])
            assignment_text = value(row, col)
            if not assignment_text:
                continue
            assignments.append(
                {
                    "source_sheet": worksheet.title,
                    "source_cell": worksheet.cell(row, col).coordinate,
                    "team": team,
                    "role": role,
                    "person_name": person_name,
                    "project_year": project["project_year"],
                    "project_name": project["project_name"],
                    "project_stage": project["project_stage"],
                    "project_manager": project["project_manager"],
                    "project_intro": project["project_intro"],
                    "project_milestone": project["project_milestone"],
                    "assignment_text": assignment_text,
                    "main_work_content": main_work,
                }
            )

    return people, assignments


def _person_key(*, team: str, role: str, person_name: str) -> str:
    raw = "|".join([team, role, person_name]).strip("|")
    return raw or person_name
