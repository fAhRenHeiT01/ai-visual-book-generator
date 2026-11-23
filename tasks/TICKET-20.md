# TICKET-20 — Print page art direction

**Status:** Open · **Predecessor:** [Ticket 19](TICKET-19.md)

Render deck-quality treatments on the shared print canvas.

## Implementation

- Implement Ticket 19's treatments in the semantic HTML/CSS renderer shared by review, draft, and print. Use asymmetric photography and pull quotes for editorial, aligned chart bands and compact grids for consulting, and large type and brand color fields for campaigns.
- Resolve surface contrast, spacing, and heading hierarchy from book tokens. Scope Studio selectors so they cannot override the canvas. Keep overflow healing, master chrome, and protected media behavior intact.
- Use the three fixed review fixtures at physical size in A4 and US Letter. Review both options before recording visual baselines.

## TDD and acceptance

**First failing test.** Render a fixture for each direction and assert concrete DOM or computed-style differences in hierarchy and media placement.

- Inspect a photo opener, paired charts, and portrait testimonial under both A/B options. Check legibility, spacing, clipping, overlap, and chart containment.
- Check preview and draft against print for each paper size. PDF page counts, searchable text, and the configured visual drift threshold pass.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/web/src/engine/PageCanvas.tsx`
- `apps/web/src/engine/canvas.css`
- `apps/web/src/engine/blocks/SemanticBlock.tsx`
- `apps/web/src/engine/archetypes/layouts.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/tests/unit/PageCanvas.test.tsx`
- `apps/web/tests/e2e/export.spec.ts`
- `apps/web/src/engine/blocks/ImageFrame.tsx`
- `apps/web/tests/e2e/page_design.spec.ts`
- `apps/web/tests/e2e/page_design.spec.ts-snapshots/`
