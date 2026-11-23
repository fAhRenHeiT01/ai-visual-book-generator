"""JSON-safe checkpoint state; canonical schemas validate at every boundary."""

from typing import Any, TypedDict


class PageState(TypedDict, total=False):
    session_id: str
    context: dict[str, Any]
    text: str
    assets: list[dict[str, Any]]
    page_id: str
    page_number: int
    blocks: list[dict[str, Any]]
    metrics_ledger: list[dict[str, Any]]
    profile_issues: list[dict[str, Any]]
    options: list[dict[str, Any]]
    validation_issues: list[dict[str, Any]]
    repair_attempts: int
    used_fallback: bool
    result: dict[str, Any]
    selection: str
    current_page_index: int
    rolling_layout_history: list[str]
    rhythm_history: list[dict[str, Any]]
