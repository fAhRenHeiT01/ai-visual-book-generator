# TICKET-17 — Source span grouping

**Status:** Open · **Predecessor:** [Ticket 16](TICKET-16.md)

Let the model group exact source spans once per page.

## Implementation

- Derive ordered spans with stable IDs and offsets on the server. Ask the model to group contiguous IDs and assign semantic roles including heading, prose, list, quote, metric, fact, or shoutout. Store the validated result before A/B generation.
- Reconstruct all text locally from the original source. Reject omissions, duplicates, invented spans and reordered groups. Fall back to deterministic grouping when model output is unusable.
- Apply privacy masking before the grouping call and keep source-bound metric classifications intact after grouping. Support a manual grouping response in the debugger. Keep the prompt, segmentation patterns and limits in YAML.

## TDD and acceptance

**First failing test.** Use a paragraph containing a testimonial and a metric without Markdown markers. Assert that A and B use the same role-labelled, exact source slices.

- Cover Unicode, repeated identical sentences, CRLF, malformed grouping, restricted metrics, restart, and a manual debug interrupt. Check exact substring validation for promoted excerpts.
- One successful grouping result serves both options and their repairs. Existing saved pages with their prior block IDs still render.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/domain/grouping.py`
- `apps/api/src/bookgen/adapters/llm/mock.py`
- `apps/api/src/bookgen/graph/nodes.py`
- `apps/api/src/bookgen/config/llm.py`
- `apps/api/src/bookgen/schemas/__init__.py`
- `apps/api/src/bookgen/schemas/debug.py`
- `apps/api/src/bookgen/config/profiling.py`
- `apps/api/src/bookgen/graph/state.py`
- `apps/api/src/bookgen/graph/workflow.py`
- `apps/api/src/bookgen/graph/debug.py`
- `apps/api/src/bookgen/adapters/llm/manual.py`
- `apps/api/src/bookgen/adapters/llm/gemini.py`
- `apps/api/src/bookgen/domain/profiler.py`
- `config/profiling.yaml`
- `config/prompts/group_spans.yaml`
- `apps/api/tests/graph/test_page_graph.py`
- `apps/api/tests/unit/test_grouping.py`
- `apps/api/tests/graph/test_debug_graph.py`
- `apps/web/tests/e2e/debug_flow.spec.ts`
- `apps/api/src/bookgen/adapters/ports.py`
- `apps/api/src/bookgen/domain/compliance.py`
- `apps/api/tests/integration/test_debug_routes.py`
- `apps/web/src/components/studio/DebugPanel.tsx`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
