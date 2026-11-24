"""Debug-only, JSON-safe inspection and checkpoint-bound resume contracts."""
from typing import Any, Literal

from pydantic import Field

from bookgen.schemas import PageGenerationResult, StrictModel, ValidationIssue
from bookgen.schemas.publishing import AppearanceResponse


class DebugInterrupt(StrictModel):
    event: Literal["llm_request", "review"]
    option_id: str | None = Field(default=None, description="group_spans for source grouping; option_a/option_b for layout requests.")
    prompt: str | None = Field(default=None, description="Copyable chat prompt containing the actual instructions, context and response schema.")
    request: dict[str, Any] | None = None
    page: PageGenerationResult | None = None


class DebugTimelineEntry(StrictModel):
    node: str
    status: Literal["completed", "paused"]
    node_input: dict[str, Any] = Field(default_factory=dict)
    node_output: dict[str, Any] = Field(default_factory=dict)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    review: PageGenerationResult | None = None


class DebugSnapshot(StrictModel):
    session_id: str
    studio_active: bool = Field(default=False, description="An unfinished ordinary page owns this session; resume it in Studio.")
    checkpoint_id: str | None = None
    status: Literal["idle", "paused", "completed"]
    next_nodes: list[str] = Field(default_factory=list)
    last_node: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    node_input: dict[str, Any] = Field(default_factory=dict)
    node_output: dict[str, Any] = Field(default_factory=dict)
    interrupts: list[DebugInterrupt] = Field(default_factory=list)
    timeline: list[DebugTimelineEntry] = Field(default_factory=list)
    appearance: AppearanceResponse


class DebugStepRequest(StrictModel):
    checkpoint_id: str = Field(min_length=1)
    response: str | None = Field(default=None, description="Unmodified LLM JSON text, or option_a/option_b at review. Omit at node boundaries.")
