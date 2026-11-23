"""Deterministic source profiling; no provider calls or body-copy mutation."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import re

from PIL import Image, UnidentifiedImageError

from bookgen.adapters.ports import StorageAdapter
from bookgen.config import load_settings
from bookgen.config.profiling import ProfilingConfig
from bookgen.schemas import AssetKind, AtomicTextBlock, ImageAssetMeta, ValidationIssue


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    filename: str = ""
    kind: AssetKind | None = None
    alt_caption: str = ""


@dataclass(frozen=True)
class ProfileResult:
    blocks: list[AtomicTextBlock]
    assets: list[ImageAssetMeta]
    issues: list[ValidationIssue]


def _parse_blocks(text: str, config: ProfilingConfig) -> list[AtomicTextBlock]:
    patterns = config.block_patterns
    groups: list[tuple[str, str]] = []
    lines: list[str] = []
    current_kind = "paragraph"

    def flush() -> None:
        if lines:
            groups.append((current_kind, "".join(lines).rstrip("\r\n")))
            lines.clear()

    for line in text.splitlines(keepends=True):
        if re.fullmatch(patterns.blank, line):
            flush()
            continue
        kind = next((name for name in ("heading", "list", "quote") if re.match(getattr(patterns, name), line)), "paragraph")
        if kind != current_kind or kind == "heading":
            flush()
        current_kind = kind
        lines.append(line)
    flush()
    return [
        AtomicTextBlock(
            block_id=f"blk_{index:02d}", kind=kind, text=source,
            word_count=len(re.findall(patterns.word, source)), char_count=len(source),
        )
        for index, (kind, source) in enumerate(groups, start=1)
    ]


def _classify(image: ImageInput, config: ProfilingConfig) -> AssetKind:
    if image.kind is not None:
        return AssetKind(image.kind)
    hints = f"{image.filename} {image.alt_caption}"
    for kind, patterns in config.chart_heuristics.items():
        if any(re.search(pattern, hints) for pattern in patterns):
            return kind
    return AssetKind.PHOTO


def _profile_image(
    source: ImageInput, asset_id: str, storage: StorageAdapter, config: ProfilingConfig,
) -> tuple[ImageAssetMeta, list[ValidationIssue]]:
    try:
        with Image.open(BytesIO(source.data)) as check:
            check.verify()
        with Image.open(BytesIO(source.data)) as image:
            image.load()
            mime_type = Image.MIME[image.format]
            if mime_type not in config.allowed_mime_types:
                raise ValueError(f"Unsupported image MIME type: {mime_type}")
            width, height = image.size
            dpi = image.info.get("dpi")
            estimated_dpi = round(min(dpi)) if dpi else None
            thumbnail = None
            if max(width, height) > config.thumbnail_max_px:
                image.thumbnail((config.thumbnail_max_px, config.thumbnail_max_px), Image.Resampling.LANCZOS)
                thumbnail = BytesIO()
                if image.mode == "CMYK":
                    with image.convert("RGB") as preview:
                        preview.save(thumbnail, format="PNG")
                else:
                    image.save(thumbnail, format="PNG")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(f"Corrupt or invalid image: {asset_id}") from exc

    ratio = width / height
    issues = []
    if estimated_dpi is not None and estimated_dpi < config.min_dpi:
        issues.append(ValidationIssue(
            code="LOW_DPI", severity="warning", target_option=asset_id,
            message=f"Image resolution is {estimated_dpi} DPI; recommended minimum is {config.min_dpi} DPI.",
        ))
    if not config.aspect_ratio_min <= ratio <= config.aspect_ratio_max:
        issues.append(ValidationIssue(
            code="ASPECT_RATIO_OUT_OF_RANGE", severity="warning", target_option=asset_id,
            message=f"Image aspect ratio {ratio:g} is outside {config.aspect_ratio_min:g}–{config.aspect_ratio_max:g}.",
        ))
    # Content addressing prevents another page's img_01 from replacing this upload.
    identity = f"{sha256(source.data).hexdigest()}/{asset_id}"
    return ImageAssetMeta(
        asset_id=asset_id,
        storage_key=storage.put(f"originals/{identity}", source.data),
        thumbnail_key=storage.put(f"thumbnails/{identity}.png", thumbnail.getvalue()) if thumbnail is not None else None,
        mime_type=mime_type, width_px=width, height_px=height, aspect_ratio=ratio,
        estimated_dpi=estimated_dpi, asset_kind=_classify(source, config), alt_caption=source.alt_caption,
    ), issues


def profile_content(
    text: str,
    images: Sequence[ImageInput] = (),
    *,
    storage: StorageAdapter,
    settings: ProfilingConfig | None = None,
) -> ProfileResult:
    """Return stable source pointers, metadata and nonblocking preflight issues.

    Images contain original bytes, optional filename/caption classification hints,
    and an optional explicit asset kind. Whitespace inside a text block is retained;
    blank lines and terminal line endings delimit blocks. Keys come from the
    injected storage adapter and can be filesystem paths or remote object keys.
    """
    config = settings if settings is not None else load_settings().profiling
    if config is None:
        raise ValueError("Profiling settings are not configured")
    config.require_complete()
    assets, issues = [], []
    for index, image in enumerate(images, start=1):
        asset, warnings = _profile_image(image, f"img_{index:02d}", storage, config)
        assets.append(asset)
        issues.extend(warnings)
    return ProfileResult(blocks=_parse_blocks(text, config), assets=assets, issues=issues)
