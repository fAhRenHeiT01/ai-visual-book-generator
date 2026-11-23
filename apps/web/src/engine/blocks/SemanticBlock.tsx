import type { components } from "../../types/generated";
import { ImageFrame } from "./ImageFrame";

type S = components["schemas"];
export const surfaceClasses: Record<S["SurfaceRole"], string> = {
  paper: "surface-paper", surface_tint: "surface-tint", brand_dark: "surface-brand-dark", accent_soft: "surface-accent-soft",
};

export function SemanticBlock({ component, blocks, assets, fullBleed }: {
  component: S["PlacedComponent"];
  blocks: ReadonlyMap<string, S["AtomicTextBlock"]>;
  assets: ReadonlyMap<string, S["ImageAssetMeta"]>;
  fullBleed: boolean;
}) {
  const source = (component.source_block_ids ?? []).flatMap((id) => {
    const block = blocks.get(id);
    return block ? [block] : [];
  });
  const className = `semantic-block block-${component.component_type} ${surfaceClasses[component.surface_role]}${component.emphasis ? " is-emphasized" : ""}`;
  const attrs = { className, "data-component-id": component.component_id, "data-slot": component.slot_id };
  switch (component.component_type) {
    case "image_frame": {
      const asset = component.source_asset_id ? assets.get(component.source_asset_id) : undefined;
      return asset ? <div {...attrs}><ImageFrame asset={asset} objectFit={component.object_fit} fullBleed={fullBleed} /></div> : null;
    }
    case "pull_quote":
    case "stat_callout": {
      const excerpt = component.extracted_excerpt;
      // Verify against a single referenced source, never concatenated blocks or generated copy.
      if (!excerpt || !source.some((block) => block.text.includes(excerpt))) return null;
      return component.component_type === "pull_quote"
        ? <blockquote {...attrs}>{excerpt}</blockquote>
        : <aside {...attrs}>{excerpt}</aside>;
    }
    case "heading":
      return <div {...attrs}>{source.map((block) => <h2 key={block.block_id} data-source-block-id={block.block_id}>{block.text}</h2>)}</div>;
    case "body_prose":
      return <div {...attrs}>{source.map((block) => <p key={block.block_id} data-source-block-id={block.block_id}>{block.text}</p>)}</div>;
    case "bullet_list":
      return <ul {...attrs}>{source.map((block) => <li key={block.block_id} data-source-block-id={block.block_id}>{block.text}</li>)}</ul>;
    case "caption":
      return <div {...attrs}>{source.map((block) => <p key={block.block_id} data-source-block-id={block.block_id}>{block.text}</p>)}</div>;
    case "divider_rule":
      return <hr {...attrs} />;
  }
}
