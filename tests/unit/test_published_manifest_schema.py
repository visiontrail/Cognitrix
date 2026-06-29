from __future__ import annotations

import pytest

from apps.api.published_pages import PublishedChartSnapshot, SnapshotWriter


@pytest.mark.parametrize(
    ("canvas_format_id", "expected_kind"),
    [
        ("web-design", "web_page"),
        ("a4-portrait", "fixed_size"),
        ("infinite", "free_layout"),
    ],
)
def test_snapshot_writer_creates_schema_v2_manifest_for_canvas_modes(
    tmp_path,
    canvas_format_id: str,
    expected_kind: str,
) -> None:
    writer = SnapshotWriter(upload_dir=tmp_path, max_rows=10)
    layout = {"grid": {"columns": 1, "rows": [{"id": "row-1", "height": 240}]}, "zones": []}
    sidebar: list[dict[str, object]] = []
    nodes = [
        {
            "id": "chart-node",
            "type": "chartNode",
            "position": {"x": 24, "y": 32},
            "width": 320,
            "height": 240,
            "data": {
                "type": "chart",
                "assetId": "chart-1",
                "title": "Headcount",
                "chartType": "bar",
                "spec": {"private": "not public"},
            },
        }
    ]

    result = writer.write(
        workspace_id="workspace-1",
        version=1,
        canvas_format_id=canvas_format_id,
        viewport={"x": 1, "y": 2, "zoom": 0.75},
        nodes=nodes,
        edges=[{"id": "edge-1", "source": "chart-node", "target": "chart-node"}],
        web_design={"layout": layout, "sidebar": sidebar},
        layout=layout,
        sidebar=sidebar,
        charts=[
            PublishedChartSnapshot(
                chart_id="chart-1",
                title="Headcount",
                chart_type="bar",
                spec={"chart_type": "bar", "title": "Headcount"},
                rows=[{"department": "HR", "headcount": 4}],
            )
        ],
        actor_role="viewer",
        published_at="2026-06-25T00:00:00Z",
        background_preset_id="graphite",
    )

    manifest = result.manifest
    assert manifest["schema_version"] == 2
    assert manifest["canvas"]["format_id"] == canvas_format_id
    assert manifest["canvas"]["kind"] == expected_kind
    assert manifest["canvas"]["background_preset_id"] == "graphite"
    assert manifest["charts"][0]["chart_id"] == "chart-1"

    if expected_kind == "web_page":
        assert manifest["content"]["web_design"]["layout"] == layout
        assert manifest["layout"] == layout
    else:
        assert "layout" not in manifest
        assert manifest["content"]["nodes"][0]["data"] == {
            "type": "chart",
            "assetId": "chart-1",
            "title": "Headcount",
            "chartType": "bar",
        }

    if expected_kind == "fixed_size":
        assert manifest["canvas"]["page"] == {
            "preset_id": "a4-portrait",
            "width": 794,
            "height": 1123,
            "count": 1,
            "gap": 48,
        }
    if expected_kind == "free_layout":
        assert manifest["canvas"]["bounds"]["width"] == 320
