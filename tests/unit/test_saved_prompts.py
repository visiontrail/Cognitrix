from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.saved_prompts import (
    SavedPromptError,
    SavedPromptStore,
    extract_variables,
    validate_capabilities,
)


# ---------------------------------------------------------------------------
# Variable parser (task 3.1)
# ---------------------------------------------------------------------------
def test_extract_single_variable() -> None:
    assert extract_variables("Recommendation for {country}") == ["country"]


def test_extract_preserves_first_seen_order() -> None:
    assert extract_variables("Analyze {department} in {month}") == ["department", "month"]


def test_repeated_exact_variable_collapses() -> None:
    body = "Compare {department} headcount with {department} attrition"
    assert extract_variables(body) == ["department"]


def test_case_ambiguous_variable_rejected() -> None:
    with pytest.raises(SavedPromptError) as exc:
        extract_variables("Compare {Department} with {department}")
    assert exc.value.code == "PROMPT_VARIABLE_AMBIGUOUS"


def test_malformed_variable_rejected() -> None:
    with pytest.raises(SavedPromptError) as exc:
        extract_variables("Compare {2026_month}")
    assert exc.value.code == "PROMPT_VARIABLE_INVALID"


def test_unterminated_variable_rejected() -> None:
    with pytest.raises(SavedPromptError) as exc:
        extract_variables("Compare {department")
    assert exc.value.code == "PROMPT_VARIABLE_INVALID"


def test_escaped_braces_are_literal() -> None:
    body = 'Return JSON like \\{\\"department\\": \\"{department}\\"\\}'
    assert extract_variables(body) == ["department"]


def test_double_braces_are_not_variables() -> None:
    assert extract_variables("Localized {{not_a_var}} text") == []


def test_no_variables_returns_empty() -> None:
    assert extract_variables("Summarize this table") == []


# ---------------------------------------------------------------------------
# Capability allowlist
# ---------------------------------------------------------------------------
def test_validate_capabilities_dedupes() -> None:
    assert validate_capabilities(["multi_chart", "data_labels", "multi_chart"]) == [
        "multi_chart",
        "data_labels",
    ]


def test_validate_capabilities_rejects_unknown() -> None:
    with pytest.raises(SavedPromptError) as exc:
        validate_capabilities(["raw_execute_sql"])
    assert exc.value.code == "PROMPT_CAPABILITY_INVALID"


# ---------------------------------------------------------------------------
# Store (task 3.2)
# ---------------------------------------------------------------------------
@pytest.fixture()
def store(tmp_path: Path) -> SavedPromptStore:
    return SavedPromptStore(db_path=tmp_path / "saved_prompts.sqlite3")


def test_create_extracts_variables(store: SavedPromptStore) -> None:
    prompt = store.create(
        owner_user_id="alice",
        name="Travel vaccine",
        body="What is the travel vaccine recommendation for {country}",
        capabilities=[],
    )
    assert prompt["id"]
    assert prompt["variables"] == ["country"]
    assert prompt["usage_count"] == 0
    assert prompt["archived_at"] is None


def test_list_filters_by_owner_and_query(store: SavedPromptStore) -> None:
    store.create(owner_user_id="alice", name="Travel vaccine", body="travel for {country}", capabilities=[])
    store.create(owner_user_id="alice", name="Attrition", body="attrition by dept", capabilities=[])
    store.create(owner_user_id="bob", name="Travel other", body="travel other", capabilities=[])

    matches = store.list(owner_user_id="alice", query="travel")
    assert [p["name"] for p in matches] == ["Travel vaccine"]

    everything = store.list(owner_user_id="alice")
    assert len(everything) == 2


def test_list_orders_used_prompts_first(store: SavedPromptStore) -> None:
    first = store.create(owner_user_id="alice", name="First", body="first body", capabilities=[])
    store.create(owner_user_id="alice", name="Second", body="second body", capabilities=[])
    # A prompt that has been used sorts ahead of never-used prompts regardless
    # of creation order (NULL last_used_at is pushed last).
    store.mark_used(owner_user_id="alice", prompt_id=first["id"])
    assert [p["name"] for p in store.list(owner_user_id="alice")][0] == "First"


def test_update_recalculates_variables(store: SavedPromptStore) -> None:
    prompt = store.create(owner_user_id="alice", name="Analyze", body="Analyze {department}", capabilities=[])
    updated = store.update(
        owner_user_id="alice",
        prompt_id=prompt["id"],
        name=None,
        body="Analyze {department} for {month}",
        capabilities=None,
    )
    assert updated["variables"] == ["department", "month"]
    assert updated["updated_at"] >= prompt["updated_at"]


def test_archive_hides_from_default_list(store: SavedPromptStore) -> None:
    prompt = store.create(owner_user_id="alice", name="Temp", body="temp body", capabilities=[])
    store.archive(owner_user_id="alice", prompt_id=prompt["id"])
    assert store.list(owner_user_id="alice") == []
    assert len(store.list(owner_user_id="alice", include_archived=True)) == 1


def test_archived_prompt_cannot_be_used(store: SavedPromptStore) -> None:
    prompt = store.create(owner_user_id="alice", name="Temp", body="temp body", capabilities=[])
    store.archive(owner_user_id="alice", prompt_id=prompt["id"])
    with pytest.raises(SavedPromptError) as exc:
        store.mark_used(owner_user_id="alice", prompt_id=prompt["id"])
    assert exc.value.code == "PROMPT_ARCHIVED"


def test_active_name_uniqueness_per_owner(store: SavedPromptStore) -> None:
    store.create(owner_user_id="alice", name="Report", body="body", capabilities=[])
    with pytest.raises(SavedPromptError) as exc:
        store.create(owner_user_id="alice", name="report", body="body2", capabilities=[])
    assert exc.value.code == "PROMPT_NAME_TAKEN"
    # different owner can reuse the name
    other = store.create(owner_user_id="bob", name="Report", body="body", capabilities=[])
    assert other["id"]


def test_archived_name_can_be_reused(store: SavedPromptStore) -> None:
    prompt = store.create(owner_user_id="alice", name="Report", body="body", capabilities=[])
    store.archive(owner_user_id="alice", prompt_id=prompt["id"])
    reused = store.create(owner_user_id="alice", name="Report", body="body2", capabilities=[])
    assert reused["id"] != prompt["id"]


def test_mark_used_increments_metadata(store: SavedPromptStore) -> None:
    prompt = store.create(owner_user_id="alice", name="Report", body="body", capabilities=[])
    used = store.mark_used(owner_user_id="alice", prompt_id=prompt["id"])
    assert used["usage_count"] == 1
    assert used["last_used_at"] is not None


def test_get_unknown_prompt_raises_not_found(store: SavedPromptStore) -> None:
    with pytest.raises(SavedPromptError) as exc:
        store.get(owner_user_id="alice", prompt_id="missing")
    assert exc.value.code == "PROMPT_NOT_FOUND"


def test_owner_isolation_in_store(store: SavedPromptStore) -> None:
    prompt = store.create(owner_user_id="alice", name="Secret", body="secret body", capabilities=[])
    with pytest.raises(SavedPromptError) as exc:
        store.get(owner_user_id="bob", prompt_id=prompt["id"])
    assert exc.value.code == "PROMPT_NOT_FOUND"
