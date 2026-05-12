from __future__ import annotations

from pathlib import Path

from apps.api.agentic_ingestion.nonstructured_excel import (
    inspect_nonstructured_workbook,
    load_primary_structured_dataframe,
)


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "sample_data"
    / "project_management_nonstructure.xlsx"
)


def test_project_assignment_matrix_inspection_extracts_structured_candidates() -> None:
    candidate = inspect_nonstructured_workbook(workbook_path=SAMPLE_PATH)

    assert candidate is not None
    assert candidate["kind"] == "project_assignment_matrix"
    assert candidate["stats"]["project_count"] == 20
    assert candidate["stats"]["assignment_count"] == 111

    seed = candidate["recommended_catalog_seed"]
    assert seed["business_type"] == "project_progress"
    assert seed["table_name"] == "project_assignments"
    assert seed["match_columns"] == ["source_cell"]

    tables = {item["table_name"]: item for item in candidate["candidate_tables"]}
    assert {"projects", "people", "project_assignments"} <= set(tables)
    assert tables["project_assignments"]["sample_rows"][0]["source_cell"] == "D8"
    assert tables["project_assignments"]["sample_rows"][0]["person_name"] == "付强"
    assert tables["project_assignments"]["sample_rows"][0]["project_name"] == "灵犀06\n（星云第一标段）"


def test_project_assignment_matrix_loads_primary_fact_dataframe() -> None:
    frame = load_primary_structured_dataframe(SAMPLE_PATH)

    assert frame is not None
    assert len(frame) == 111
    assert list(frame.columns) == [
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
    assert frame.iloc[0]["source_cell"] == "D8"
