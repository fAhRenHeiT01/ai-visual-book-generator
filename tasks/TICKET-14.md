# TICKET-14 — Metadata-only provider requests

**Status:** Open · **Predecessor:** [Ticket 13](TICKET-13.md)

Send asset metadata to layout providers.

## Implementation

- Use one allowlisted projection for initial, repair, and manual prompts. Include asset ID, kind, dimensions, aspect ratio, available caption, and resolution information. Keep provider context bounded and apply existing privacy rules.
- Remove binary image reads, base64, storage paths, SDK image parts, and debug downloads from layout requests. A future VLM can populate descriptive or crop metadata in a separate pass.
- Project old paused interrupts and recorded exchanges into the metadata-only presentation while preserving the original checkpoint identity for resume.

## TDD and acceptance

**First failing test.** Use a storage double that fails on reads and capture the final SDK request and manual prompt for an uploaded chart.

- Initial generation and repair both succeed with text and metadata. Inspect actual serialized parts and copied prompts for bytes, attachment instructions, URLs, and filesystem paths.
- Resume an old checkpoint containing inline image parts. Assert that the debug response hides the bytes and the original checkpoint still advances exactly once.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/adapters/llm/gemini.py`
- `apps/api/src/bookgen/graph/debug.py`
- `apps/api/src/bookgen/schemas/debug.py`
- `apps/api/src/bookgen/adapters/llm/manual.py`
- `config/prompts/debug_chat.yaml`
- `apps/web/src/components/studio/DebugPanel.tsx`
- `apps/api/tests/unit/test_gemini_adapter.py`
- `apps/api/tests/graph/test_debug_graph.py`
- `apps/web/tests/unit/DebugPanel.test.tsx`
- `apps/web/tests/e2e/debug_flow.spec.ts`
- `apps/api/tests/integration/test_debug_routes.py`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
