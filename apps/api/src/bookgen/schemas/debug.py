"""Debug-only, JSON-safe inspection and checkpoint-bound resume contracts."""
from typing import Any, Literal

from pydantic import Field

from bookgen.schemas import PageGenerationResult, StrictModel
from bookgen.schemas.publishing import AppearanceResponse


class DebugImageAttachment(StrictModel):
    asset_id: str
    mime_type: Literal["image/png"]
    data: str = Field(description="Base64-encoded provider thumbnail to attach beside the chat prompt.")


class DebugInterrupt(StrictModel):
    event: Literal["llm_request", "review"]
    option_id: str | None = None
    prompt: str | None = Field(default=None, description="Copyable chat prompt containing the actual instructions, context and response schema.")
    images: list[DebugImageAttachment] = Field(default_factory=list)
    request: dict[str, Any] | None = None
    page: PageGenerationResult | None = None


class DebugSnapshot(StrictModel):
    session_id: str
    checkpoint_id: str | None = None
    status: Literal["idle", "paused", "completed"]
    next_nodes: list[str] = Field(default_factory=list)
    last_node: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    node_input: dict[str, Any] = Field(default_factory=dict)
    node_output: dict[str, Any] = Field(default_factory=dict)
    interrupts: list[DebugInterrupt] = Field(default_factory=list)
    appearance: AppearanceResponse


class DebugStepRequest(StrictModel):
    checkpoint_id: str = Field(min_length=1)
    response: str | None = Field(default=None, description="Unmodified LLM JSON text, or option_a/option_b at review. Omit at node boundaries.")
