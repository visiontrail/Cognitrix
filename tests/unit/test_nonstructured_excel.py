from __future__ import annotations

from pathlib import Path

from apps.api.agentic_ingestion.nonstructured_excel import inspect_workbook_structure


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"
NONSTRUCTURED_SAMPLE = SAMPLE_DIR / "project_management_nonstructure.xlsx"
FLAT_HR_ROSTER = SAMPLE_DIR / "gs_hr_roster.xlsx"
FLAT_HR_WORKFORCE_SAMPLE = SAMPLE_DIR / "hr_workforce_upload_sample.xlsx"


def test_inspect_workbook_structure_emits_no_business_labels() -> None:
    """The inspector must never invent business names or labels. It only
    reports neutral structural signals so the agent can classify the layout."""

    summary = inspect_workbook_structure(workbook_path=NONSTRUCTURED_SAMPLE)
    assert summary is not None

    serialized = repr(summary)
    for forbidden in (
        "项目人员投入分配",
        "项目维表",
        "人员维表",
        "项目人员投入分配事实表",
        "recommended_catalog_seed",
        "project_assignment_matrix",
        "primary_table",
    ):
        assert forbidden not in serialized, f"unexpected hardcoded token in summary: {forbidden}"


def test_nonstructured_project_workbook_is_flagged_as_human_readable_matrix() -> None:
    summary = inspect_workbook_structure(workbook_path=NONSTRUCTURED_SAMPLE)
    assert summary is not None

    sheet = summary["sheets"][0]
    signals = sheet["structural_signals"]
    assert signals["has_merged_cells"] is True
    assert signals["has_stacked_top_metadata"] is True
    assert signals["likely_layout"] == "human_readable_matrix"
    assert sheet["merged_cell_count"] > 0
    assert sheet["top_rows_preview"]


def test_flat_hr_roster_is_not_misdetected_as_project_matrix() -> None:
    """Regression: a clean HR roster with team/role/name columns must NOT be
    misclassified as a project assignment matrix and must NOT inherit any
    hardcoded label from a different sample."""

    summary = inspect_workbook_structure(workbook_path=FLAT_HR_ROSTER)
    assert summary is not None

    primary_sheet = summary["sheets"][0]
    signals = primary_sheet["structural_signals"]
    assert signals["likely_layout"] == "flat_table"
    assert signals["has_stacked_top_metadata"] is False

    serialized = repr(summary)
    assert "项目人员投入分配" not in serialized
    assert "project_assignments" not in serialized


def test_flat_workforce_sample_is_flat_table() -> None:
    summary = inspect_workbook_structure(workbook_path=FLAT_HR_WORKFORCE_SAMPLE)
    assert summary is not None

    primary_sheet = summary["sheets"][0]
    signals = primary_sheet["structural_signals"]
    assert signals["likely_layout"] == "flat_table"
