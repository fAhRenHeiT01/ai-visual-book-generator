# TICKET-11 — Manual graph debugger verification

The existing opt-in debugger was verified end to end. It already provides durable
node boundaries, manual initial/repair responses, YAML-framed chat prompts from
the effective Gemini request, separate bounded image attachments, strict
validation/fallback, checkpoint-bound actions, legacy SDK-only interrupt
conversion, and actual renderer/theme inspection.

## Concrete correction

LangGraph replays an interrupted node on resume. If prompt configuration changed
after a pause or API restart, replay recorded the new request/prompt against the
reply copied from the original pause. Bind each manual reply to its persisted
request and prompt in the resume value, then use that pair in durable node
exchanges. Preserve support for older checkpoints containing string resumes.
The public API and generated contracts are unchanged.

## TDD evidence

Added `test_resumed_response_keeps_the_prompt_and_payload_the_user_copied` before
production changes. Running the focused test with `pytest -W error` produced
**1 failed, 8 deselected**. The expected assertion failed because the recorded
exchange request contained `Updated after restart.` while the original request
did not. The regression now passes. A second regression verifies replay of an
older string resume across restart. Both use `MockLLMProvider` and assert that it
receives no calls.

## Verification

- Python unit, graph, and integration suites: **234 passed**, `-W error`.
- Focused debugger graph suite: **10 passed**, `-W error`.
- Frontend unit suite: **58 passed**.
- TypeScript `tsc --noEmit`: passed.
- Contract check (`scripts/sync_contracts.sh --check`): passed; no regeneration
  required because no schema changed.
- Debug Chromium E2E: **1 passed**, including refresh, image attachments, actual
  theme rendering, manual responses, and explicit commit.
- Normal Chromium E2E: **2 passed**, covering three-page persistence and approved
  PDF download with metric redaction and numbered chrome.
- `git diff --check`: passed.

The first full Python attempt had three PDF fixture setup errors because Next.js
Turbopack rejected dependencies linked outside the worktree. Copying the shared
dependency files into the ignored worktree `node_modules` directory resolved
this; the final full gate above passed. Windows Playwright server teardown needed
manual cleanup of its test server processes after browser assertions completed.

The JavaScript tooling emits the existing Node 26 `DEP0205` deprecation warning
for `module.register()`. Therefore the JavaScript gates pass, but their output is
not warning-free. No unrelated dependency or runtime files were changed.

## Files changed

- `apps/api/src/bookgen/graph/debug.py`
- `apps/api/src/bookgen/adapters/llm/manual.py`
- `apps/api/tests/graph/test_debug_graph.py`
- `README.md`
- `tasks/TICKET-11.md`
