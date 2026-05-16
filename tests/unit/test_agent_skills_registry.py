from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.agent_skills.registry import (
    SkillNotFoundError,
    SkillRegistry,
)


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    return SkillRegistry(db_path=tmp_path / "agent_skills.sqlite3")


def _upsert(registry: SkillRegistry, *, skill_id: str = "skill-1", name: str = "anthropic/xlsx") -> None:
    registry.upsert(
        skill_id=skill_id,
        name=name,
        version="1.0.0",
        sha256="a" * 64,
        uploaded_by="superadmin",
        bundle_dir=f"/tmp/agent_skills/{skill_id}",
        manifest={"name": name, "description": "Excel toolkit"},
    )


def test_upsert_creates_and_returns_record(registry: SkillRegistry) -> None:
    record = registry.upsert(
        skill_id="skill-1",
        name="anthropic/xlsx",
        version="1.0.0",
        sha256="b" * 64,
        uploaded_by="root",
        bundle_dir="/tmp/x",
        manifest={"name": "anthropic/xlsx", "description": "Excel"},
    )
    assert record.id == "skill-1"
    assert record.name == "anthropic/xlsx"
    assert record.status == "enabled"
    assert record.manifest["description"] == "Excel"
    assert record.load_error is None


def test_upsert_replaces_existing_record_with_same_name(registry: SkillRegistry) -> None:
    _upsert(registry, skill_id="old", name="anthropic/xlsx")
    _upsert(registry, skill_id="new", name="anthropic/xlsx")

    assert registry.get_by_name("anthropic/xlsx").id == "new"
    with pytest.raises(SkillNotFoundError):
        registry.get("old")


def test_get_missing_raises(registry: SkillRegistry) -> None:
    with pytest.raises(SkillNotFoundError):
        registry.get("nope")


def test_list_returns_records_newest_first(registry: SkillRegistry) -> None:
    _upsert(registry, skill_id="s1", name="a/1")
    _upsert(registry, skill_id="s2", name="a/2")
    records = registry.list()
    assert [r.id for r in records[:2]] == ["s2", "s1"]


def test_set_status_toggles_field(registry: SkillRegistry) -> None:
    _upsert(registry)
    record = registry.set_status("skill-1", "disabled")
    assert record.status == "disabled"
    record = registry.set_status("skill-1", "enabled")
    assert record.status == "enabled"


def test_set_status_rejects_invalid_value(registry: SkillRegistry) -> None:
    _upsert(registry)
    with pytest.raises(ValueError):
        registry.set_status("skill-1", "bogus")


def test_set_status_missing_skill_raises(registry: SkillRegistry) -> None:
    with pytest.raises(SkillNotFoundError):
        registry.set_status("missing", "enabled")


def test_set_load_error_round_trip(registry: SkillRegistry) -> None:
    _upsert(registry)
    registry.set_load_error("skill-1", "manifest invalid")
    assert registry.get("skill-1").load_error == "manifest invalid"
    registry.set_load_error("skill-1", None)
    assert registry.get("skill-1").load_error is None


def test_delete_removes_skill_and_assignments(registry: SkillRegistry) -> None:
    _upsert(registry)
    registry.assign(skill_id="skill-1", agent_name="WriteIngestionAgent", assigned_by="root")
    registry.delete("skill-1")
    with pytest.raises(SkillNotFoundError):
        registry.get("skill-1")
    # Assignment is cascade-deleted via FK.
    assert registry.list_assignments_for_agent("WriteIngestionAgent") == []


def test_delete_missing_skill_raises(registry: SkillRegistry) -> None:
    with pytest.raises(SkillNotFoundError):
        registry.delete("nope")


def test_assign_and_list_for_agent(registry: SkillRegistry) -> None:
    _upsert(registry)
    assignment = registry.assign(
        skill_id="skill-1", agent_name="WriteIngestionAgent", assigned_by="root"
    )
    assert assignment.skill_id == "skill-1"
    assert assignment.agent_name == "WriteIngestionAgent"
    listed = registry.list_assignments_for_agent("WriteIngestionAgent")
    assert len(listed) == 1
    assert listed[0].skill_id == "skill-1"


def test_assign_is_idempotent_and_updates_assigned_by(registry: SkillRegistry) -> None:
    _upsert(registry)
    first = registry.assign(skill_id="skill-1", agent_name="QueryAgent", assigned_by="root")
    second = registry.assign(skill_id="skill-1", agent_name="QueryAgent", assigned_by="ops")
    assignments = registry.list_assignments_for_agent("QueryAgent")
    assert len(assignments) == 1
    assert assignments[0].assigned_by == "ops"
    assert second.assigned_at >= first.assigned_at


def test_assign_unknown_skill_raises(registry: SkillRegistry) -> None:
    with pytest.raises(SkillNotFoundError):
        registry.assign(skill_id="missing", agent_name="QueryAgent", assigned_by="root")


def test_assign_blank_agent_name_rejected(registry: SkillRegistry) -> None:
    _upsert(registry)
    with pytest.raises(ValueError):
        registry.assign(skill_id="skill-1", agent_name="   ", assigned_by="root")


def test_unassign_returns_true_when_removed(registry: SkillRegistry) -> None:
    _upsert(registry)
    registry.assign(skill_id="skill-1", agent_name="WriteIngestionAgent", assigned_by="root")
    assert registry.unassign(skill_id="skill-1", agent_name="WriteIngestionAgent") is True
    assert registry.unassign(skill_id="skill-1", agent_name="WriteIngestionAgent") is False


def test_list_assignments_for_skill(registry: SkillRegistry) -> None:
    _upsert(registry)
    registry.assign(skill_id="skill-1", agent_name="WriteIngestionAgent", assigned_by="root")
    registry.assign(skill_id="skill-1", agent_name="QueryAgent", assigned_by="root")
    rows = registry.list_assignments_for_skill("skill-1")
    assert sorted(r.agent_name for r in rows) == ["QueryAgent", "WriteIngestionAgent"]


def test_schema_persists_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_skills.sqlite3"
    first = SkillRegistry(db_path=db_path)
    _upsert(first)
    second = SkillRegistry(db_path=db_path)
    record = second.get("skill-1")
    assert record.name == "anthropic/xlsx"
