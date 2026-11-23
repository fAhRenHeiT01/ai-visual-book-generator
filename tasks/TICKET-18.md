# TICKET-18 — Reusable theme library

**Status:** Open · **Predecessor:** [Ticket 17](TICKET-17.md)

Save reusable extracted themes across books.

## Implementation

- On successful extraction, persist a named installation-wide theme with a stable ID, source URL, and sanitized tokens. Preserve the extraction response fields existing callers use and add the saved theme identity.
- Expose the configured presets and saved themes through a list endpoint. Applying a theme is a separate author action and copies its tokens into the book's appearance. Retain the generation-time appearance lock.

## TDD and acceptance

**First failing test.** Extract a theme through a mocked website fetch, restart the API, and attempt to list it and apply it to a second book.

- The saved theme survives restart and works in another book without another fetch. Failed extraction creates no entry. Applying a different theme elsewhere leaves existing books' appearance snapshots intact.
- Test existing extraction clients, named presets, contrast sanitation, and the lock after generation starts.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/adapters/db/sqlite.py`
- `apps/api/src/bookgen/routes/theme.py`
- `apps/api/src/bookgen/schemas/publishing.py`
- `apps/api/tests/integration/test_theme_routes.py`
- `apps/api/src/bookgen/domain/theme.py`
- `apps/api/tests/integration/test_publishing_interfaces.py`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
