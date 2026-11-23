# TICKET-21 — Enterprise authoring workspace

**Status:** Open · **Predecessor:** [Ticket 20](TICKET-20.md)

Polish the enterprise authoring workspace.

## Implementation

- Organize setup, compose, option review, and draft navigation around the current authoring action. Give the page preview the largest share of the workspace. Use consistent typography, spacing, focus treatment, and status messaging.
- Show complete side-by-side A/B pages on desktop and stacked pages at smaller widths. Scale the preview wrapper while preserving its physical layout and overflow measurements.
- Expose Auto and the three explicit book directions in setup, plus the dedicated debug entry for enabled installations. Surface existing recovery, compliance, and export actions in context. Ticket 22 owns the palette editor.

## TDD and acceptance

**First failing test.** Exercise a desktop and narrow-screen review with both options and assert the complete page is visible without application-level horizontal scrolling.

- Complete create, generate, compare, select, reopen, and export by keyboard and pointer. Check empty, loading, failed, selected, and locked states.
- Verify chosen direction reaches book creation, recovery keeps page input, and application styles leave Ticket 20's canvas baselines intact.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/web/src/components/studio/Studio.tsx`
- `apps/web/src/components/setup/BookSetup.tsx`
- `apps/web/src/components/draft/DraftViewer.tsx`
- `apps/web/src/components/studio/PageComposer.tsx`
- `apps/web/src/components/studio/OptionComparison.tsx`
- `apps/web/src/components/studio/PagePreview.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/tests/unit/Studio.test.tsx`
- `apps/web/tests/e2e/mvp_flow.spec.ts`
- `apps/web/src/components/draft/ExportAction.tsx`
- `apps/web/src/components/compliance/ComplianceBanner.tsx`
- `apps/web/src/app/layout.tsx`
