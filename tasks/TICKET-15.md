# TICKET-15 — Resolution-based render derivatives

**Status:** Open · **Predecessor:** [Ticket 14](TICKET-14.md)

Use smaller images only when rendering needs a derivative.

## Implementation

- At upload, create a proportional preview only when the longest edge exceeds `profiling.thumbnail_max_px`. Start with the configured 768 px value. Make the thumbnail key optional in the canonical asset schema.
- In interactive previews select the derivative when available. Use the original below the threshold and for print/PDF at every size. Return the actual MIME type of the bytes served. Support existing assets that already have derivative keys.

## TDD and acceptance

**First failing test.** Profile images just below, exactly at, and just above the configured edge and assert the stored object count.

- Cover portrait and landscape dimensions, an original JPEG served through the preview endpoint, an old stored thumbnail, and a new asset with no thumbnail key.
- Verify URLs used in review, draft, and print. Chart and diagram rendering continues to use contain without overlays.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/domain/profiler.py`
- `apps/api/src/bookgen/schemas/__init__.py`
- `apps/api/src/bookgen/routes/sessions.py`
- `apps/web/src/lib/sessionApi.ts`
- `apps/web/src/app/print/[sessionId]/page.tsx`
- `apps/api/tests/unit/test_profiler.py`
- `apps/api/tests/integration/test_sessions.py`
- `apps/web/src/engine/blocks/ImageFrame.tsx`
- `apps/web/src/components/draft/DraftViewer.tsx`
- `apps/web/tests/unit/PageCanvas.test.tsx`
- `apps/web/tests/e2e/export.spec.ts`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
