import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ComponentType } from "react";
import type { components } from "../../src/types/generated";
import { sessionApi } from "../../src/lib/sessionApi";

type S = components["schemas"];
type CanvasProps = { result: S["PageGenerationResult"]; tokens: S["DesignTokens"]; layout?: S["PageLayoutAST"]; pageSize?: S["PageSize"]; chrome?: { config?: S["MasterChromeConfig"]; pageNumber?: number; totalPages?: number; chapterTitle?: string; isCover?: boolean } };
const modules = import.meta.glob("../../src/engine/PageCanvas.tsx", { eager: true });
const Canvas = (modules["../../src/engine/PageCanvas.tsx"] as { PageCanvas: ComponentType<CanvasProps> } | undefined)?.PageCanvas;
const shapes = {
  full_bleed_hero: "full_page", minimalist_swiss: "minimalist_swiss", section_divider: "full_page",
  editorial_asymmetric: "media_prose_split", two_col_executive: "column_flow", top_media_narrative: "top_media_narrative",
  chart_focus_band: "chart_focus_band", guided_alternating: "media_prose_split", dashboard_split: "dashboard_split",
  modular_cards: "modular_cards", safe_flow_fallback: "column_flow",
} satisfies Record<S["LayoutArchetype"], string>;
const tokens: S["DesignTokens"] = {
  theme_id: "test", palette_source: "manual", color_paper: "white", color_ink_primary: "black", color_ink_muted: "gray",
  color_brand_primary: "navy", color_brand_accent: "teal", color_surface_tint: "ivory", font_heading: "Inter",
  font_body: "Source Serif 4", radius_px: 6, page_margin_mm: 16, chrome_band_mm: 12,
};
function placed(id: string, type: S["ComponentType"], slot: string, ids: string[] = []): S["PlacedComponent"] {
  return { component_id: id, component_type: type, slot_id: slot, source_block_ids: ids, source_asset_id: null,
    extracted_excerpt: null, object_fit: "cover", surface_role: "paper", emphasis: false };
}
function fixture(archetype: S["LayoutArchetype"] = "full_bleed_hero", kinds: S["AssetKind"][] = ["chart"]): S["PageGenerationResult"] {
  const input_blocks = ["Hello—世界!", "Exact “copy”, punctuation… preserved.", "Second line: café ✓"].map((text, i) => ({ block_id: `b${i}`, text, kind: "paragraph", char_count: text.length, word_count: 4 }));
  const input_assets = kinds.map((kind, i) => ({ asset_id: `a${i}`, asset_kind: kind, storage_key: `/assets/${i}.png`, thumbnail_key: `/thumb/${i}.png`, alt_caption: `Visual ${i}`, aspect_ratio: 2, width_px: 1000, height_px: 500, mime_type: "image/png", estimated_dpi: null }));
  const layout: S["PageLayoutAST"] = { option_id: "a", archetype, rationale: "", strategy_tag: "test", density_scale: "airy", column_count: 1, surface_role: "surface_tint", components: [
    placed("h", "heading", "header", ["b0"]), placed("body", "body_prose", "body", ["b1", "b2"]),
    ...input_assets.map((asset, i) => ({ ...placed(`image${i}`, "image_frame", i ? "media_secondary" : "media_main"), source_asset_id: asset.asset_id })),
    { ...placed("quote", "pull_quote", "callout", ["b1"]), extracted_excerpt: "“copy”, punctuation…", surface_role: "accent_soft", emphasis: true },
  ] };
  return { page_id: "p1", page_number: 3, title: null, input_blocks, input_assets, option_a: layout, option_b: { ...layout, option_id: "b" }, selected_option_id: "a", metrics_ledger: [], repair_attempts: 0, used_fallback: false };
}
function mount(result = fixture(), extra: Partial<CanvasProps> = {}) {
  expect(Canvas, "PageCanvas must implement the physical page renderer").toBeDefined();
  if (!Canvas) throw new Error("Missing PageCanvas");
  const view = render(<Canvas result={result} tokens={tokens} {...extra} />);
  // jsdom does not fetch image assets. Model eager images having finished loading.
  view.container.querySelectorAll("img").forEach((image) => Object.defineProperty(image, "complete", { value: true }));
  return view;
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("PageCanvas", () => {
  test("compose thumbnail URLs encode session and asset IDs independently", () => {
    expect(sessionApi.assetThumbnailUrl("session / 1", "asset / 2")).toBe("/api/v1/sessions/session%20%2F%201/assets/asset%20%2F%202?thumbnail=true");
  });
  test.each([
    { direction: "editorial", archetype: "editorial_asymmetric", composition: "portrait_story", media_placement: "portrait_rail", surface_treatment: "plain", emphasis_treatment: "testimonial", kind: "photo" },
    { direction: "consulting", archetype: "dashboard_split", composition: "comparison", media_placement: "paired", surface_treatment: "tinted_band", emphasis_treatment: "evidence", kind: "chart" },
    { direction: "campaign", archetype: "top_media_narrative", composition: "opener", media_placement: "panoramic", surface_treatment: "brand_panel", emphasis_treatment: "headline", kind: "photo" },
  ] as const)("renders $direction hierarchy and media placement from named treatments", (treatment) => {
    const result = fixture(treatment.archetype, treatment.composition === "comparison" ? ["chart", "chart"] : [treatment.kind]);
    if (treatment.composition === "portrait_story") Object.assign(result.input_assets[0], { aspect_ratio: .8, width_px: 400, height_px: 500 });
    Object.assign(result.option_a, { composition: treatment.composition, media_placement: treatment.media_placement, surface_treatment: treatment.surface_treatment, emphasis_treatment: treatment.emphasis_treatment });
    const before = JSON.stringify(result);
    const { container } = mount(result);
    const content = screen.getByTestId("page-content");
    expect(content.classList.contains(`composition-${treatment.composition}`)).toBe(true);
    expect(content.classList.contains(`media-${treatment.media_placement}`)).toBe(true);
    expect(container.querySelector(".block-heading")?.classList.contains(`hierarchy-${treatment.emphasis_treatment}`)).toBe(true);
    expect(container.querySelector("figure")?.classList.contains(`placement-${treatment.media_placement}`)).toBe(true);
    expect(screen.getByTestId("page-canvas").getAttribute("data-surface-treatment")).toBe(treatment.surface_treatment);
    expect(container.querySelector("[data-component-id='image0']")?.getAttribute("data-asset-kind")).toBe(treatment.kind);
    expect(JSON.stringify(result)).toBe(before);
  });

  test("treatment healing restores flowing media and balanced hierarchy without changing the AST", async () => {
    vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockReturnValue(true);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    const result = fixture("top_media_narrative", ["photo"]);
    Object.assign(result.option_a, { composition: "opener", media_placement: "panoramic", emphasis_treatment: "headline", surface_treatment: "brand_panel" });
    const before = JSON.stringify(result);
    const { container } = mount(result);
    await waitFor(() => expect(screen.getByTestId("page-canvas").dataset.settled).toBe("true"));
    expect(screen.getByTestId("page-content").className).toContain("media-in_flow");
    expect(container.querySelector(".block-heading")?.className).toContain("hierarchy-balanced");
    expect(container.querySelector("figure")?.className).toContain("placement-in_flow");
    expect(JSON.stringify(result)).toBe(before);
  });
  test("review and draft use screen derivatives while print keeps original URLs", () => {
    const result = fixture("chart_focus_band", ["chart", "diagram", "photo"]);
    // Old assets retain their derivative even when their dimensions are small.
    result.input_assets[0].width_px = 320;
    result.input_assets[1].thumbnail_key = null;
    Reflect.deleteProperty(result.input_assets[2], "thumbnail_key");
    const before = JSON.stringify(result);
    const preview = sessionApi.browserPage("session 1", result);
    const base = "/api/v1/sessions/session%201/assets/";
    const { container } = mount(preview);
    const images = screen.getAllByRole("img");
    expect(images.map(image => image.getAttribute("src"))).toEqual([base + "a0", base + "a1", base + "a2"]);
    expect(container.querySelector("source")?.getAttribute("srcset")).toBe(base + "a0?thumbnail=true");
    expect(container.querySelector("source")?.getAttribute("media")).toBe("screen");
    expect(container.querySelectorAll("source")).toHaveLength(1);
    const printed = sessionApi.browserPage("session 1", result, "print");
    expect(printed.input_assets.every(asset => !asset.thumbnail_key)).toBe(true);
    expect(printed.input_assets.map(asset => asset.storage_key)).toEqual([base + "a0", base + "a1", base + "a2"]);
    expect(JSON.stringify(result)).toBe(before);
  });
  test.each(Object.keys(shapes) as S["LayoutArchetype"][])("renders %s pointers, exact excerpts and assets in reading order", async (archetype) => {
    const result = fixture(archetype);
    const before = JSON.stringify(result);
    const { container } = mount(result);
    const page = screen.getByTestId("page-canvas");
    expect(page.getAttribute("data-archetype")).toBe(archetype);
    expect(container.querySelector("[data-renderer-shape]")?.getAttribute("data-renderer-shape")).toBe(shapes[archetype]);
    const text = Array.from(container.querySelectorAll("[data-source-block-id]")).map((el) => el.textContent);
    expect(text).toEqual(result.input_blocks.map((block) => block.text));
    expect(screen.getByText("“copy”, punctuation…").className).toContain("surface-accent-soft");
    expect(screen.getByText("“copy”, punctuation…").className).toContain("is-emphasized");
    expect(screen.getByAltText("Visual 0").getAttribute("src")).toBe("/assets/0.png");
    await waitFor(() => expect(page.getAttribute("data-settled")).toBe("true"));
    expect(JSON.stringify(result)).toBe(before);
  });
  test.each(["A4", "LETTER"] as const)("uses physical %s dimensions, twelve columns and supplied token variables", (pageSize) => {
    mount(fixture(), { pageSize });
    const page = screen.getByTestId("page-canvas");
    expect(page.style.width).toBe(pageSize === "A4" ? "210mm" : "8.5in");
    expect(page.style.height).toBe(pageSize === "A4" ? "297mm" : "11in");
    expect(page.style.getPropertyValue("--page-margin")).toBe("16mm");
    expect(page.style.getPropertyValue("--chrome-band")).toBe("12mm");
    expect(page.style.getPropertyValue("--color-brand-primary")).toBe("navy");
    expect(page.style.getPropertyValue("--brand-primary")).toBe("navy");
    expect(page.style.getPropertyValue("--brand-accent")).toBe("teal");
    expect(page.style.getPropertyValue("--surface-tint")).toBe("ivory");
    expect(page.style.getPropertyValue("--font-body")).toBe("Source Serif 4");
    expect(screen.getByTestId("page-content").style.gridTemplateColumns).toBe("repeat(12, minmax(0px, 1fr))");
  });
  test.each(Object.keys(shapes) as S["LayoutArchetype"][])("protects chart and diagram media in %s", (archetype) => {
    const { container } = mount(fixture(archetype, ["chart", "diagram"]));
    for (const image of screen.getAllByRole("img")) {
      expect(image.className).toContain("object-contain");
      expect(image.className).not.toContain("object-cover");
      const frame = image.closest("figure");
      expect(frame?.getAttribute("data-protected-media")).toBe("true");
      expect(frame?.textContent).toBe("");
      expect(frame?.querySelector("[data-scrim]")).toBeNull();
    }
    expect(container.querySelector(".full-page-photo")).toBeNull();
  });
  test("full bleed photos have a cover image and a scrim", () => {
    mount(fixture("full_bleed_hero", ["photo"]));
    expect(screen.getByRole("img").className).toContain("object-cover");
    expect(screen.getByRole("img").closest("figure")?.querySelector("[data-scrim]")).not.toBeNull();
  });
  test("hydrates every semantic block and slot; rejects invented or missing excerpts", () => {
    const result = fixture("modular_cards", ["logo", "photo"]);
    result.option_a.components.push(placed("list", "bullet_list", "col_left", ["b1"]), placed("caption", "caption", "col_right", ["b2"]), placed("rule", "divider_rule", "footer"),
      { ...placed("stat", "stat_callout", "callout", ["b0"]), extracted_excerpt: "世界" },
      { ...placed("bad", "pull_quote", "callout", ["b0"]), extracted_excerpt: "invented" },
      placed("empty", "stat_callout", "callout", ["b0"]));
    const { container } = mount(result);
    expect(screen.queryByText("invented")).toBeNull();
    expect(screen.getByText("世界")).toBeTruthy();
    expect(screen.getByRole("listitem").textContent).toBe(result.input_blocks[1].text);
    expect(screen.getByRole("separator")).toBeTruthy();
    expect(container.querySelector("[data-component-id='bad']")).toBeNull();
    expect(new Set(Array.from(container.querySelectorAll("[data-slot]")).map((el) => el.getAttribute("data-slot")))).toEqual(new Set(["header", "body", "col_left", "col_right", "media_main", "media_secondary", "callout", "footer"]));
  });
  test("selects option B, supports a layout override and optional chrome with cover suppression", () => {
    const result = fixture();
    result.selected_option_id = "b";
    result.option_b = { ...result.option_b, archetype: "minimalist_swiss" };
    const config: S["MasterChromeConfig"] = { enabled: true, header_left: "Book", header_right: "{chapter_title}", footer_left: "Confidential", footer_center: "", footer_right: "Page {page_number} of {total_pages}", suppress_on_archetypes: ["section_divider"] };
    const chrome = { config, totalPages: 9, chapterTitle: "Results" };
    const view = mount(result, { chrome });
    expect(screen.getByTestId("page-canvas").getAttribute("data-archetype")).toBe("minimalist_swiss");
    expect(screen.getByText("Page 3 of 9")).toBeTruthy();
    expect(screen.getByText("Results")).toBeTruthy();
    if (!Canvas) return;
    view.rerender(<Canvas result={result} tokens={tokens} layout={{ ...result.option_a, archetype: "section_divider" }} chrome={chrome} />);
    expect(screen.queryByText("Book")).toBeNull();
    view.rerender(<Canvas result={result} tokens={tokens} chrome={{ ...chrome, isCover: true }} />);
    expect(screen.queryByText("Page 3 of 9")).toBeNull();
  });
  test("renders a local two-column safe flow after all densities overflow and preserves persisted layout", async () => {
    vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockReturnValue(true);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    const result = fixture("full_bleed_hero", ["photo"]);
    const before = JSON.stringify(result);
    const { container } = mount(result);
    const page = screen.getByTestId("page-canvas");
    await waitFor(() => expect(page.dataset.settled).toBe("true"));
    expect(page.dataset.safeFlow).toBe("true");
    expect(page.dataset.overflow).toBe("true");
    expect(page.dataset.density).toBe("compact");
    expect(screen.getByTestId("page-content").className).toContain("healed-safe-flow");
    expect(screen.getByTestId("page-content").dataset.rendererShape).toBe("column_flow");
    expect(screen.getByTestId("page-content").className).toContain("archetype-safe_flow_fallback");
    expect(container.querySelector("[data-scrim]")).toBeNull();
    expect(JSON.stringify(result)).toBe(before);
  });
  test("handles absent optional pointers and refuses excerpts spanning distinct source blocks", () => {
    const result = fixture("minimalist_swiss");
    result.selected_option_id = null;
    result.option_a.surface_role = "brand_dark";
    result.option_a.components.push(
      { ...placed("cross-block", "pull_quote", "callout", ["b0", "b1"]), extracted_excerpt: `${result.input_blocks[0].text}${result.input_blocks[1].text}` },
      { ...placed("missing-block", "body_prose", "body", ["unknown"]), source_block_ids: undefined },
      placed("missing-asset", "image_frame", "media_main"),
      { ...placed("unknown-asset", "image_frame", "media_main"), source_asset_id: "unknown" },
    );
    const { container } = mount(result);
    expect(screen.getByTestId("page-canvas").className).toContain("surface-brand-dark");
    expect(container.querySelector("[data-component-id='cross-block']")).toBeNull();
    expect(container.querySelector("[data-component-id='missing-block']")?.textContent).toBe("");
    expect(container.querySelector("[data-component-id='missing-asset']")).toBeNull();
    expect(container.querySelector("[data-component-id='unknown-asset']")).toBeNull();
  });
});
