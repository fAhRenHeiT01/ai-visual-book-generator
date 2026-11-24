"""JSON-safe checkpoint state; canonical schemas validate at every boundary."""

from typing import Any, TypedDict


class PageState(TypedDict, total=False):
    debug_mode: bool
    debug_last_node: str | None
    debug_node_input: dict[str, Any]
    debug_node_output: dict[str, Any]
    debug_exchanges: list[dict[str, Any]]
    session_id: str
    context: dict[str, Any]
    text: str
    title: str | None
    page_title: str
    assets: list[dict[str, Any]]
    page_id: str
    page_number: int
    blocks: list[dict[str, Any]]
    source_spans: list[dict[str, Any]]
    source_grouping: dict[str, Any] | None
    grouping_used_fallback: bool
    metrics_ledger: list[dict[str, Any]]
    profile_issues: list[dict[str, Any]]
    options: list[dict[str, Any]]
    validation_issues: list[dict[str, Any]]
    repair_attempts: int
    used_fallback: bool
    result: dict[str, Any] | None
    selection: str
    current_page_index: int
    rolling_layout_history: list[str]
    rhythm_history: list[dict[str, Any]]
