import type { ReactNode, RefObject } from "react";
import type { components } from "../../types/generated";

export type ShapeProps = {
  children: ReactNode;
  contentRef: RefObject<HTMLDivElement | null>;
  archetype: components["schemas"]["LayoutArchetype"];
  photoBackground: boolean;
  safeFlow: boolean;
  composition?: components["schemas"]["PageLayoutAST"]["composition"];
  mediaPlacement?: components["schemas"]["PageLayoutAST"]["media_placement"];
};
function Grid({ children, contentRef, archetype, photoBackground, safeFlow, shape, composition = "flow", mediaPlacement = "in_flow" }: ShapeProps & { shape: string }) {
  return <div ref={contentRef} data-testid="page-content" data-renderer-shape={shape}
    className={`page-content shape-${shape} archetype-${archetype} composition-${composition} media-${mediaPlacement}${photoBackground ? " full-page-photo" : ""}${safeFlow ? " healed-safe-flow" : ""}`}
    style={{ gridTemplateColumns: "repeat(12, minmax(0, 1fr))" }}>{children}</div>;
}
export function FullPage(props: ShapeProps) { return <Grid {...props} shape="full_page" />; }
export function MediaProseSplit(props: ShapeProps) { return <Grid {...props} shape="media_prose_split" />; }
export function ColumnFlow(props: ShapeProps) { return <Grid {...props} shape="column_flow" />; }
export function MinimalistSwiss(props: ShapeProps) { return <Grid {...props} shape="minimalist_swiss" />; }
export function TopMediaNarrative(props: ShapeProps) { return <Grid {...props} shape="top_media_narrative" />; }
export function ChartFocusBand(props: ShapeProps) { return <Grid {...props} shape="chart_focus_band" />; }
export function DashboardSplit(props: ShapeProps) { return <Grid {...props} shape="dashboard_split" />; }
export function ModularCards(props: ShapeProps) { return <Grid {...props} shape="modular_cards" />; }

export const archetypeRenderers = {
  full_bleed_hero: FullPage, section_divider: FullPage,
  editorial_asymmetric: MediaProseSplit, guided_alternating: MediaProseSplit,
  two_col_executive: ColumnFlow, safe_flow_fallback: ColumnFlow,
  minimalist_swiss: MinimalistSwiss, top_media_narrative: TopMediaNarrative,
  chart_focus_band: ChartFocusBand, dashboard_split: DashboardSplit, modular_cards: ModularCards,
} satisfies Record<components["schemas"]["LayoutArchetype"], (props: ShapeProps) => ReactNode>;
