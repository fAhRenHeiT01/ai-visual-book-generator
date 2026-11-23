# TICKET-12 — Recover failed page generation

**Status:** Open · **Predecessor:** [Ticket 11](TICKET-11.md)

Generate a page safely after an interrupted request.

## Implementation

- Give the client a durable page identity before the first generation attempt. Extend the existing session snapshot with enough state to reopen the active page after a refresh, including its saved asset IDs.
- Retrying the same input resumes the failed checkpoint. If review or commit already succeeded, return that page. An explicit revision of a failed page starts from its edited input under the same page ID and number. Reopen a saved review after a browser render failure.
- Reserve `409` on page creation for a competing unfinished page. Distinguish input errors, provider schema rejection, and transient upstream failure. Exercise the existing SDK schema serialization with a fake transport. The observed upstream errors are regression examples, and the original reported 500 has no confirmed cause.

## TDD and acceptance

**First failing test.** Inject a provider failure after checkpoint creation. Reopen the session with a fresh service and assert that the same request can reach review.

- Test unchanged retry, revised input, lost response, concurrent duplicates, legacy unfinished checkpoints, and a conflicting new page. Assert a single committed page and the correct next page number.
- Refresh Studio after failure with uploaded images. Retry reuses uploads. A revision accepts replacement inputs. A saved result can be rendered again without another provider call.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/graph/workflow.py`
- `apps/api/src/bookgen/graph/state.py`
- `apps/api/src/bookgen/routes/sessions.py`
- `apps/api/src/bookgen/schemas/sessions.py`
- `apps/web/src/components/studio/PageComposer.tsx`
- `apps/web/src/lib/sessionApi.ts`
- `apps/web/src/components/studio/Studio.tsx`
- `apps/api/tests/integration/test_sessions.py`
- `apps/api/tests/graph/test_page_graph.py`
- `apps/web/tests/unit/Studio.test.tsx`
- `apps/api/src/bookgen/adapters/db/sqlite.py`
- `apps/api/src/bookgen/adapters/llm/gemini.py`
- `apps/api/tests/unit/test_gemini_adapter.py`
- `apps/web/tests/e2e/mvp_flow.spec.ts`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
