import type { components } from "../../types/generated";

export function ImageFrame({ asset, objectFit, fullBleed = false }: {
  asset: components["schemas"]["ImageAssetMeta"];
  objectFit: string;
  fullBleed?: boolean;
}) {
  const protectedMedia = asset.asset_kind === "chart" || asset.asset_kind === "diagram";
  const background = fullBleed && asset.asset_kind === "photo";
  const fit = !protectedMedia && objectFit === "cover" ? "object-cover" : "object-contain";
  return (
    <figure className={`image-frame ${background ? "photo-background" : ""}`} data-protected-media={protectedMedia}>
      {/* The original asset is used for preview and print; thumbnails are only for provider context. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={asset.storage_key} alt={asset.alt_caption} className={fit} loading="eager" decoding="sync" />
      {background && <span className="photo-scrim" data-scrim aria-hidden="true" />}
    </figure>
  );
}
