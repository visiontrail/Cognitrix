"""LLM-powered schema inference for arbitrary Excel uploads.

When a file contains many unrecognized columns (e.g. pure Chinese headers),
this module calls an OpenAI-compatible LLM to infer:
  1. A canonical snake_case English name for every column
  2. A semantic type (string | number | datetime | boolean)
  3. A set of auto-generated metrics appropriate for the data

The output is persisted as a JSON "schema overlay" file alongside the batch
metadata and is loaded at query time by the semantic layer.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("cognitrix.schema_inference")

# Max sample values sent per column to the LLM (keeps prompt small)
_MAX_SAMPLE_VALUES = 5

_SYSTEM_PROMPT = """\
You are a data-schema analyst. Given a list of spreadsheet column names \
(which may be in Chinese or mixed language) and sample values, return a JSON \
object with two keys:

"columns": an object mapping each original column name (exactly as given) \
to an object with:
  - "canonical": a concise lowercase English snake_case identifier \
(max 40 chars, no spaces, no Chinese). Must be globally unique.
  - "type": one of "string" | "number" | "datetime" | "boolean"
  - "label": a human-readable label in the same language as the input (preserve \
Chinese when present)

"metrics": an array of metric objects auto-derived from numeric / count-able \
columns. Each metric has:
  - "name": snake_case English metric id (unique)
  - "label": human-readable label (Chinese preferred)
  - "kind": one of "count_distinct" | "sum" | "avg" | "count"
  - "column": the *canonical* column name this metric targets
  - "description": one sentence in English

Rules:
- Every original column MUST appear exactly once in "columns".
- For columns that already look like valid English snake_case, keep them as-is \
in "canonical" (still emit the entry).
- Emit ONLY the JSON object, no markdown fences, no commentary.
"""


def _build_user_prompt(
    column_samples: dict[str, list[Any]],
) -> str:
    lines: list[str] = ["Columns and sample values:"]
    for col, samples in column_samples.items():
        clean = [str(v) for v in samples if v is not None and str(v).strip() not in ("", "nan", "NaT")][:_MAX_SAMPLE_VALUES]
        lines.append(f"  {col!r}: {clean}")
    return "\n".join(lines)


def _chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def infer_schema(
    *,
    column_samples: dict[str, list[Any]],
    ai_api_key: str,
    ai_model: str = "claude-haiku-4-5-20251001",
    ai_base_url: str = "https://api.anthropic.com/v1",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call an OpenAI-compatible LLM to infer column mapping and metrics.

    Returns a dict with keys ``columns`` and ``metrics`` as described in the
    system prompt.  On any failure, returns an empty overlay so the caller can
    continue without schema enrichment.
    """
    user_msg = _build_user_prompt(column_samples)

    logger.info("schema_inference_request column_count=%d model=%s", len(column_samples), ai_model)

    payload = {
        "model": ai_model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    }

    endpoint = _chat_completions_endpoint(ai_base_url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ai_api_key}",
    }
    req = urllib_request.Request(endpoint, data=body, headers=headers, method="POST")
    started_at = time.perf_counter()

    raw_text = ""
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw_response = resp.read().decode("utf-8")

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        data = json.loads(raw_response)
        choices = data.get("choices") or []
        if not choices:
            logger.warning("schema_inference_failed error=empty choices from LLM")
            return {"columns": {}, "metrics": []}

        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        raw_text = content.strip() if isinstance(content, str) else ""

        # Strip markdown code fences if the model added them anyway
        raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
        raw_text = re.sub(r"\n?```$", "", raw_text)
        result: dict[str, Any] = json.loads(raw_text)
        logger.info(
            "schema_inference_success column_count=%d metric_count=%d elapsed_ms=%s",
            len(result.get("columns", {})),
            len(result.get("metrics", [])),
            elapsed_ms,
        )
        return result
    except json.JSONDecodeError as exc:
        logger.warning("schema_inference_parse_error raw=%r error=%s", raw_text[:200], exc)
        return {"columns": {}, "metrics": []}
    except (TimeoutError, socket.timeout) as exc:
        logger.warning("schema_inference_failed error=timeout: %s", exc)
        return {"columns": {}, "metrics": []}
    except urllib_error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        logger.warning("schema_inference_failed error=HTTP %s: %s", exc.code, details or exc.reason)
        return {"columns": {}, "metrics": []}
    except Exception as exc:
        logger.warning("schema_inference_failed error=%s", exc)
        return {"columns": {}, "metrics": []}


def build_column_samples(dataframe: "pd.DataFrame", max_rows: int = 5) -> dict[str, list[Any]]:  # type: ignore[name-defined]
    """Extract a small sample per column for the inference prompt."""
    samples: dict[str, list[Any]] = {}
    for col in dataframe.columns:
        non_null = dataframe[col].dropna()
        values = non_null.head(max_rows).tolist()
        samples[str(col)] = values
    return samples


def apply_overlay_to_dataframe(
    dataframe: "pd.DataFrame",  # type: ignore[name-defined]
    overlay: dict[str, Any],
) -> "pd.DataFrame":  # type: ignore[name-defined]
    """Rename DataFrame columns using the LLM-inferred canonical names."""
    columns_map: dict[str, Any] = overlay.get("columns", {})
    rename: dict[str, str] = {}
    used: set[str] = set()

    for original_col in dataframe.columns:
        original_str = str(original_col)
        info = columns_map.get(original_str)
        if info and isinstance(info, dict):
            canonical = str(info.get("canonical", original_str)).strip() or original_str
        else:
            canonical = original_str

        # Ensure uniqueness
        base = canonical
        suffix = 1
        while canonical in used:
            suffix += 1
            canonical = f"{base}_{suffix}"
        used.add(canonical)
        if canonical != original_str:
            rename[original_str] = canonical

    return dataframe.rename(columns=rename)


def save_schema_overlay(
    *,
    meta_dir: Path,
    batch_id: str,
    overlay: dict[str, Any],
    column_mapping: dict[str, str],
) -> Path:
    """Persist the LLM-inferred overlay as a JSON sidecar next to batch metadata."""
    payload = {
        "batch_id": batch_id,
        "column_mapping": column_mapping,
        "columns": overlay.get("columns", {}),
        "metrics": overlay.get("metrics", []),
    }
    target = meta_dir / f"{batch_id}_schema_overlay.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("schema_overlay_saved path=%s", target)
    return target


def load_schema_overlay(*, meta_dir: Path, batch_id: str) -> dict[str, Any] | None:
    """Load a previously saved schema overlay, or return None if absent."""
    target = meta_dir / f"{batch_id}_schema_overlay.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("schema_overlay_load_failed path=%s error=%s", target, exc)
        return None


def should_run_inference(unrecognized_columns: list[str], total_columns: int) -> bool:
    """Return True whenever any column needs LLM-driven canonicalisation.

    The previous implementation gated inference behind an arbitrary 40%
    threshold. Any unrecognised column is now enough to trigger the LLM,
    letting the model decide what to canonicalise rather than relying on a
    magic ratio.
    """
    _ = total_columns
    return bool(unrecognized_columns)
