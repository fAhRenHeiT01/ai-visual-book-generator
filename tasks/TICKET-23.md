# TICKET-23 — Interactive examples and golden gates

**Status:** Open · **Predecessor:** [Ticket 22](TICKET-22.md)

Open example books and run golden regressions in CI.

## Implementation

- Add an Examples entry in Studio backed by the Ticket 13 catalog. Open a scenario as an isolated book with its own assets and deterministic sample responses. Use the normal generation, review, compliance and export paths.
- Run all 25 cases offline and a 20-page non-repetition sequence. Measure source and asset coverage, excerpt fidelity, protected media, overflow, compliance, and preview/PDF parity. Observe the architecture's first-pass validity target of at least 90% on ordinary cases and report deliberate repair cases separately.
- Record reviewed screenshots across the three directions and representative PDFs. Label the results as scripted fixture runs, and wire the golden suite into the normal test runner and CI.

## TDD and acceptance

**First failing test.** Open the same example twice and assert distinct session identities and independently reviewable pages. Add an offline manifest-driven regression test for all scenarios.

- Every example opens without a provider key or an external asset fetch. Editing or committing in one instance leaves the other untouched.
- Verify zero source hallucination or drop, no consecutive repeated archetype in the 20-page sequence, and configured PDF drift bounds. Restricted cases show the expected compliance gate before export.
- Publish the contact sheets or screenshot comparisons and representative PDFs as CI artifacts with the case IDs and art directions.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/examples/`
- `apps/api/src/bookgen/routes/examples.py`
- `apps/api/src/bookgen/main.py`
- `apps/api/src/bookgen/schemas/sessions.py`
- `apps/api/src/bookgen/graph/workflow.py`
- `apps/api/src/bookgen/adapters/llm/examples.py`
- `apps/web/src/components/setup/Examples.tsx`
- `apps/web/src/components/studio/Studio.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/src/lib/sessionApi.ts`
- `apps/api/tests/golden/`
- `apps/web/tests/e2e/examples.spec.ts`
- `Makefile`
- `.github/workflows/ci.yml`
- `README.md`
- `apps/api/pyproject.toml`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
