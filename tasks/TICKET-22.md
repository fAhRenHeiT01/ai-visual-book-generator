# TICKET-22 — Theme library and palette UI

**Status:** Open · **Predecessor:** [Ticket 21](TICKET-21.md)

Make the theme library and palette editor usable in Studio.

## Implementation

- Replace the free-text preset field with selectable theme cards. Show role names, color swatches, editable hex values, contrast feedback, and a miniature live preview rendered through the shared canvas.
- Use the Ticket 18 API. Successful extraction creates a named library entry. Let the author inspect it and explicitly apply it to the current book. Display extraction errors, invalid color input, saved state, and read-only locked appearance.

## TDD and acceptance

**First failing test.** Extract in one session using a mocked fetch, open the picker in another session, and assert the saved palette is selectable by keyboard.

- Selecting or editing a palette updates the draft preview. Only applying updates book appearance. Editing a role retains the other colors and chrome settings.
- Check focus order, accessible swatch names, error recovery, extraction progress, and a locked book.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/web/src/components/setup/ThemeControls.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/src/lib/sessionApi.ts`
- `apps/web/tests/unit/ThemeControls.test.tsx`
- `apps/web/tests/e2e/theme_library.spec.ts`
