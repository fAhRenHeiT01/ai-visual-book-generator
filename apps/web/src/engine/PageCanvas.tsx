"use client";

import { useRef, type CSSProperties } from "react";
import type { components } from "../types/generated";
import { archetypeRenderers, ColumnFlow } from "./archetypes/layouts";
import { SemanticBlock, surfaceClasses } from "./blocks/SemanticBlock";
import { useOverflowHeal } from "./useOverflowHeal";
import { MasterChrome, chromeBands } from "./MasterChrome";
import "./canvas.css";

type S = components["schemas"];
export type ChromeContext = {
  config?: S["MasterChromeConfig"];
  pageNumber?: number;
  totalPages?: number;
  chapterTitle?: string;
  isCover?: boolean;
};
export type PageCanvasProps = {
  result: S["PageGenerationResult"];
  tokens: S["DesignTokens"];
  layout?: S["PageLayoutAST"];
  pageSize?: S["PageSize"];
  chrome?: ChromeContext;
};

export function PageCanvas({ result, tokens, layout: override, pageSize = "A4", chrome }: PageCanvasProps) {
  const layout = override ?? (result.selected_option_id === result.option_b.option_id ? result.option_b : result.option_a);
  const contentRef = useRef<HTMLDivElement>(null);
  const resetKey = JSON.stringify([tokens, pageSize, chrome, result.input_blocks, result.input_assets]);
  const heal = useOverflowHeal(contentRef, layout, resetKey);
  const Renderer = heal.safeFlow ? ColumnFlow : archetypeRenderers[layout.archetype];
  const blocks = new Map(result.input_blocks.map((block) => [block.block_id, block]));
  const assets = new Map(result.input_assets.map((asset) => [asset.asset_id, asset]));
  const composition = heal.safeFlow ? "flow" : layout.composition ?? "flow";
  const mediaPlacement = heal.safeFlow ? "in_flow" : layout.media_placement ?? "in_flow";
  const emphasis = heal.safeFlow ? "balanced" : layout.emphasis_treatment ?? "balanced";
  const fullPage = !heal.safeFlow && (layout.archetype === "full_bleed_hero" || layout.archetype === "section_divider");
  const media = layout.components.filter((component) => component.component_type === "image_frame");
  const photoBackground = fullPage && mediaPlacement === "in_flow" && media.length === 1 && assets.get(media[0].source_asset_id ?? "")?.asset_kind === "photo";
  const config = chrome?.config;
  const bands = chromeBands(config, !!chrome?.isCover || layout.archetype === "full_bleed_hero" || layout.archetype === "section_divider" || !!config?.suppress_on_archetypes?.includes(layout.archetype));
  const chromeValues = { pageNumber: chrome?.pageNumber ?? result.page_number, totalPages: chrome?.totalPages, chapterTitle: chrome?.chapterTitle };
  const style = {
    width: pageSize === "A4" ? "210mm" : "8.5in", height: pageSize === "A4" ? "297mm" : "11in",
    "--color-paper": tokens.color_paper, "--color-ink-primary": tokens.color_ink_primary, "--color-ink-muted": tokens.color_ink_muted,
    "--color-brand-primary": tokens.color_brand_primary, "--color-brand-accent": tokens.color_brand_accent, "--color-surface-tint": tokens.color_surface_tint,
    "--brand-primary": tokens.color_brand_primary, "--brand-accent": tokens.color_brand_accent, "--surface-tint": tokens.color_surface_tint,
    "--font-heading": tokens.font_heading, "--font-body": tokens.font_body, "--radius-base": `${tokens.radius_px}px`,
    "--page-margin": `${tokens.page_margin_mm}mm`, "--chrome-band": `${tokens.chrome_band_mm}mm`,
    "--chrome-header-band": bands.header ? `${tokens.chrome_band_mm}mm` : "0mm", "--chrome-footer-band": bands.footer ? `${tokens.chrome_band_mm}mm` : "0mm",
  } as CSSProperties;

  return <article data-testid="page-canvas" data-page-id={result.page_id} data-page-size={pageSize} data-archetype={layout.archetype}
    data-density={heal.density} data-safe-flow={heal.safeFlow} data-settled={heal.settled} data-overflow={heal.overflow}
    data-chrome-header={bands.header} data-chrome-footer={bands.footer}
    data-surface-treatment={heal.safeFlow ? "plain" : layout.surface_treatment ?? "plain"}
    className={`page-canvas ${surfaceClasses[layout.surface_role]}${photoBackground ? " has-full-bleed" : ""}`} style={style}>
    {bands.header && config && <MasterChrome config={config} band="header" values={chromeValues} />}
    <Renderer contentRef={contentRef} archetype={heal.safeFlow ? "safe_flow_fallback" : layout.archetype} photoBackground={photoBackground} safeFlow={heal.safeFlow} composition={composition} mediaPlacement={mediaPlacement}>
      {layout.components.map((component) => <SemanticBlock key={component.component_id} component={component} blocks={blocks} assets={assets} fullBleed={photoBackground} emphasis={emphasis} mediaPlacement={mediaPlacement} />)}
    </Renderer>
    {bands.footer && config && <MasterChrome config={config} band="footer" values={chromeValues} />}
  </article>;
}
