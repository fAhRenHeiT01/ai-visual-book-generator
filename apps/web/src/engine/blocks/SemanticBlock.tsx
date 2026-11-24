import type { ReactNode } from "react";
import type { components } from "../../types/generated";
import { ImageFrame } from "./ImageFrame";

type S = components["schemas"];
export const surfaceClasses: Record<S["SurfaceRole"], string> = {
  paper: "surface-paper", surface_tint: "surface-tint", brand_dark: "surface-brand-dark", accent_soft: "surface-accent-soft",
};

/** Offsets from Python are code points, so slice Unicode characters rather than UTF-16 units. */
export function ReviewText({ text, metrics = [], sourceOffset = 0 }: {
  text: string; metrics?: S['ComplianceMetric'][]; sourceOffset?: number;
}) {
  const characters = Array.from(text);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  const sorted = [...metrics].sort((a, b) => (a.source_start ?? 0) - (b.source_start ?? 0));
  for (const item of sorted) {
    if (item.source_start == null || item.source_end == null) continue;
    const start = item.source_start - sourceOffset, end = item.source_end - sourceOffset;
    // A changed source or an older report without offsets must never mark a different occurrence.
    if (start < cursor || start < 0 || end > characters.length || start >= end ||
      characters.slice(start, end).join('') !== item.metric.raw_value) continue;
    nodes.push(characters.slice(cursor, start).join(''));
    nodes.push(<span key={item.metric.metric_id} className={`compliance-metric review-${item.decision ?? 'pending'}`}
      data-metric-id={item.metric.metric_id} data-decision={item.decision ?? 'pending'}
      title={item.decision === 'approve' ? 'Approved' : item.decision === 'redact' ? 'Redacted for export' : 'Needs review'}>{characters.slice(start, end).join('')}</span>);
    cursor = end;
  }
  nodes.push(characters.slice(cursor).join(''));
  return <>{nodes}</>;
}

export function SemanticBlock({ component, blocks, assets, fullBleed, emphasis = "balanced", mediaPlacement = "in_flow", reviewMetrics }: {
  component: S["PlacedComponent"];
  blocks: ReadonlyMap<string, S["AtomicTextBlock"]>;
  assets: ReadonlyMap<string, S["ImageAssetMeta"]>;
  fullBleed: boolean;
  emphasis?: S["PageLayoutAST"]["emphasis_treatment"];
  mediaPlacement?: S["PageLayoutAST"]["media_placement"];
  reviewMetrics?: S['ComplianceMetric'][];
}) {
  const source = (component.source_block_ids ?? []).flatMap((id) => {
    const block = blocks.get(id);
    return block ? [block] : [];
  });
  const className = `semantic-block block-${component.component_type} ${surfaceClasses[component.surface_role]} hierarchy-${emphasis}${component.emphasis ? " is-emphasized" : ""}`;
  const attrs = { className, "data-component-id": component.component_id, "data-slot": component.slot_id };
  const metricsFor = (block: S['AtomicTextBlock']) => reviewMetrics?.filter(item =>
    item.metric.source_block_id === block.block_id && item.metric.context_snippet === block.text);
  const textFor = (block: S['AtomicTextBlock']) => <ReviewText text={block.text} metrics={metricsFor(block)} />;
  switch (component.component_type) {
    case "image_frame": {
      const asset = component.source_asset_id ? assets.get(component.source_asset_id) : undefined;
      return asset ? <div {...attrs} data-asset-kind={asset.asset_kind}><ImageFrame asset={asset} objectFit={component.object_fit} fullBleed={fullBleed} placement={mediaPlacement} /></div> : null;
    }
    case "pull_quote":
    case "stat_callout": {
      const excerpt = component.extracted_excerpt;
      // Verify against a single referenced source, never concatenated blocks or generated copy.
      if (!excerpt || !source.some((block) => block.text.includes(excerpt))) return null;
      const matches = source.flatMap(block => {
        const start = block.text.indexOf(excerpt);
        // Excerpt pointers have no occurrence offset. Ambiguous excerpts stay unmarked.
        return start >= 0 ? [{ block, start, unique: block.text.indexOf(excerpt, start + 1) < 0 }] : [];
      });
      const match = matches.length === 1 && matches[0].unique ? matches[0] : undefined;
      const text = match ? <ReviewText text={excerpt} metrics={metricsFor(match.block)} sourceOffset={Array.from(match.block.text.slice(0, match.start)).length} /> : excerpt;
      return component.component_type === "pull_quote"
        ? <blockquote {...attrs}>{text}</blockquote>
        : <aside {...attrs}>{text}</aside>;
    }
    case "heading":
      return <div {...attrs}>{source.map((block) => <h2 key={block.block_id} data-source-block-id={block.block_id}>{textFor(block)}</h2>)}</div>;
    case "body_prose":
      return <div {...attrs}>{source.map((block) => <p key={block.block_id} data-source-block-id={block.block_id}>{textFor(block)}</p>)}</div>;
    case "bullet_list":
      return <ul {...attrs}>{source.map((block) => <li key={block.block_id} data-source-block-id={block.block_id}>{textFor(block)}</li>)}</ul>;
    case "caption":
      return <div {...attrs}>{source.map((block) => <p key={block.block_id} data-source-block-id={block.block_id}>{textFor(block)}</p>)}</div>;
    case "divider_rule":
      return <hr {...attrs} />;
  }
}
