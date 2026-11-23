"""Deterministic, non-mutating structural gate for a pair of pointer ASTs."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
import json
from typing import Any

from pydantic import ValidationError

from bookgen.config import load_settings
from bookgen.config.grammar import GrammarConfig
from bookgen.schemas import (
    AtomicTextBlock, ComponentType, ImageAssetMeta, LayoutArchetype,
    PageLayoutAST, ValidationIssue,
)


def deterministic_validator(
    options: Sequence[PageLayoutAST | Mapping[str, Any]],
    source_blocks: Sequence[AtomicTextBlock],
    source_assets: Sequence[ImageAssetMeta],
    recent_archetypes: Sequence[LayoutArchetype | str] = (),
    *, grammar: GrammarConfig | None = None,
) -> list[ValidationIssue]:
    """Parse both options and report all domain violations without repairing input.

    Budgets use actual source text rather than trusting caller-supplied counts.
    Excerpts supplement full source placement and never satisfy completeness.
    """
    grammar = grammar if grammar is not None else load_settings().grammar
    blocks = {b.block_id: b for b in source_blocks}
    assets = {a.asset_id: a for a in source_assets}
    rules = grammar.archetypes()
    issues: list[ValidationIssue] = []

    def issue(code: str, target: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, severity="error", message=message,
                                      target_option=target))

    parsed = []
    for option in options:
        raw = option.model_dump(warnings=False) if isinstance(option, PageLayoutAST) else option
        target = str(raw.get("option_id", "unknown")) if isinstance(raw, Mapping) else "unknown"
        try:
            # JSON strict mode accepts canonical enum strings but rejects scalar coercion.
            page = PageLayoutAST.model_validate_json(json.dumps(dict(raw) if isinstance(raw, Mapping) else raw), strict=True)
        except (ValidationError, TypeError, ValueError) as exc:
            issue("SCHEMA_VALIDATION_ERROR", target, str(exc))
            continue
        parsed.append(page)
        rule = rules[page.archetype]
        if page.archetype in recent_archetypes:
            issue("RECENT_ARCHETYPE_REPEAT", target, "Archetype is excluded by recent history.")
        if page.density_scale not in grammar.density_scales:
            issue("INVALID_DENSITY_SCALE", target, "Density is not defined by the grammar.")

        placed_blocks: set[str] = set()
        placed_assets: set[str] = set()
        slot_chars: dict[str, int] = defaultdict(int)
        text_slots: set[str] = set()
        protected_slots: set[str] = set()
        for component in page.components:
            ids = component.source_block_ids
            unknown = set(ids) - blocks.keys()
            if unknown:
                issue("UNKNOWN_BLOCK_ID", target, f"Unknown block IDs: {sorted(unknown)}")
            if component.component_type in grammar.body_component_types:
                placed_blocks.update(ids)
                slot_chars[component.slot_id] += sum(len(blocks[i].text) for i in ids if i in blocks)
            if component.component_type in grammar.excerpt_component_types:
                excerpt = component.extracted_excerpt
                if not excerpt or not ids or not any(i in blocks and excerpt in blocks[i].text for i in ids):
                    issue("HALLUCINATED_EXCERPT", target, f"{component.component_id}: excerpt must match a referenced source exactly.")
                slot_chars[component.slot_id] += len(excerpt or "")
            if ids or component.component_type in grammar.excerpt_component_types:
                text_slots.add(component.slot_id)
            if component.object_fit not in grammar.object_fits:
                issue("INVALID_OBJECT_FIT", target, f"{component.component_id}: undefined object fit.")

            slot = rule.slots.get(component.slot_id)
            if slot is None:
                issue("UNKNOWN_SLOT", target, f"Slot {component.slot_id} is not defined for this archetype.")
            elif component.component_type not in grammar.slot_role_components[slot.role]:
                issue("SLOT_ROLE_MISMATCH", target, f"{component.component_id}: component is not permitted in slot {component.slot_id}.")

            asset_id = component.source_asset_id
            if asset_id is not None:
                if asset_id not in assets:
                    issue("UNKNOWN_ASSET_ID", target, f"Unknown asset ID: {asset_id}")
                else:
                    if component.component_type == ComponentType.IMAGE_FRAME:
                        placed_assets.add(asset_id)
                    else:
                        issue("ASSET_COMPONENT_MISMATCH", target, "Assets must be placed in image frames.")
                    if assets[asset_id].asset_kind in grammar.protected_asset_kinds:
                        protected_slots.add(component.slot_id)
                        if component.object_fit != grammar.protected_object_fit:
                            issue("CHART_CROP_FORBIDDEN", target, f"{asset_id}: protected media requires contain.")

        missing_blocks = blocks.keys() - placed_blocks
        if missing_blocks:
            issue("MISSING_BLOCK_ID", target, f"Missing full source placements: {sorted(missing_blocks)}")
        missing_assets = assets.keys() - placed_assets
        if missing_assets:
            issue("MISSING_ASSET_ID", target, f"Missing assets: {sorted(missing_assets)}")
        if grammar.forbid_protected_overlay and protected_slots & text_slots:
            issue("CHART_CROP_FORBIDDEN", target, "Protected media cannot share a text overlay slot.")
        media_slots = {c.slot_id for c in page.components if c.source_asset_id is not None}
        for slot_id in media_slots & text_slots:
            slot = rule.slots.get(slot_id)
            if slot is not None and not slot.allows_overlay:
                issue("SLOT_OVERLAY_FORBIDDEN", target, f"Slot {slot_id} does not permit overlays.")
        for slot_id, chars in slot_chars.items():
            slot = rule.slots.get(slot_id)
            if slot is not None and slot.max_chars is not None and chars > slot.max_chars:
                issue("SLOT_OVERFLOW_BUDGET", target, f"Slot {slot_id} exceeds its character budget.")
        words = sum(len(b.text.split()) for b in source_blocks)
        if rule.max_words is not None and words > rule.max_words:
            issue("ARCHETYPE_OVERFLOW_BUDGET", target, "Source text exceeds the archetype word budget.")
        if rule.max_images is not None and len(placed_assets) > rule.max_images:
            issue("ARCHETYPE_IMAGE_BUDGET", target, "Assets exceed the archetype image budget.")

    if len(options) != 2 or [p.option_id for p in parsed] != ["option_a", "option_b"]:
        issue("INVALID_OPTION_PAIR", "pair", "Expected option_a followed by option_b.")
    if len(parsed) == 2 and rules[parsed[0].archetype].family == rules[parsed[1].archetype].family:
        issue("DUPLICATE_STRATEGY", parsed[1].option_id, "Options must use distinct archetype families.")
    return issues
