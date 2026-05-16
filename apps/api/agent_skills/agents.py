"""Named-agent registry.

The agent runtime, the chart query agent, and the ingestion agent each have a
canonical logical name used for skill assignment. Keeping the list in one place
makes assignment validation and runtime lookup symmetric.
"""

from __future__ import annotations

from typing import Final


WRITE_INGESTION_AGENT: Final[str] = "WriteIngestionAgent"
QUERY_AGENT: Final[str] = "QueryAgent"
CHART_QUERY_AGENT: Final[str] = "ChartQueryAgent"


NAMED_AGENTS: Final[tuple[str, ...]] = (
    WRITE_INGESTION_AGENT,
    QUERY_AGENT,
    CHART_QUERY_AGENT,
)


def is_known_agent(name: str) -> bool:
    return name.strip() in NAMED_AGENTS
