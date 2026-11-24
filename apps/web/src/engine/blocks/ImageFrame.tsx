import type { components } from "../../types/generated";

export function ImageFrame({ asset, objectFit, fullBleed = false, placement = "in_flow" }: {
  asset: components["schemas"]["ImageAssetMeta"];
  objectFit: string;
  fullBleed?: boolean;
  placement?: components["schemas"]["PageLayoutAST"]["media_placement"];
}) {
  const protectedMedia = asset.asset_kind === "chart" || asset.asset_kind === "diagram";
  const background = fullBleed && asset.asset_kind === "photo";
  const fit = !protectedMedia && objectFit === "cover" ? "object-cover" : "object-contain";
  return (
    <figure className={`image-frame placement-${placement} ${background ? "photo-background" : ""}`} data-protected-media={protectedMedia}>
      <picture>
        {/* Browser printing selects the original when the screen source no longer matches. */}
        {asset.thumbnail_key && <source media="screen" srcSet={asset.thumbnail_key} />}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={asset.storage_key} alt={asset.alt_caption} className={fit} loading="eager" decoding="sync" />
      </picture>
      {background && <span className="photo-scrim" data-scrim aria-hidden="true" />}
    </figure>
  );
}
