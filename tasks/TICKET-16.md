# TICKET-16 — Dedicated debug workspace

**Status:** Open · **Predecessor:** [Ticket 15](TICKET-15.md)

Move manual debugging to a dedicated session workspace.

## Implementation

- Use `/sessions/[sessionId]/debug` for manual generation. Treat the server flag as a capability. Regular Studio remains available while the debugger is enabled.
- Reuse the normal graph definition and Ticket 12's page ownership rules. Put checkpoint inspection, manual input, stale-step handling, and stepping behind the debugger interface. Show an ordered timeline with current node, input, output, validation issues, and review.
- Open previously paused manual runs at their saved checkpoint. Allow explicit selection and commit only through the appropriate workflow for the active page.

## TDD and acceptance

**First failing test.** Enable the debugger and start a normal page through the ordinary endpoint. In a separate session start and reopen a manual run.

- Normal authoring succeeds with the capability enabled. A manual run makes zero live provider calls, survives restart, rejects stale submissions and prevents a competing page.
- Browser coverage exercises copying a prompt, submitting responses, inspecting a validation or repair step, reviewing A/B and committing from the dedicated route.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/graph/workflow.py`
- `apps/api/src/bookgen/graph/debug.py`
- `apps/api/src/bookgen/schemas/debug.py`
- `apps/web/src/app/sessions/[sessionId]/debug/page.tsx`
- `apps/web/src/components/studio/Studio.tsx`
- `apps/web/src/components/studio/DebugPanel.tsx`
- `apps/api/tests/integration/test_debug_routes.py`
- `apps/api/tests/graph/test_debug_graph.py`
- `apps/web/tests/unit/Studio.test.tsx`
- `apps/web/tests/e2e/debug_flow.spec.ts`
- `apps/api/src/bookgen/routes/debug.py`
- `apps/api/src/bookgen/adapters/llm/manual.py`
- `apps/web/src/lib/sessionApi.ts`
- `apps/web/tests/unit/DebugPanel.test.tsx`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
