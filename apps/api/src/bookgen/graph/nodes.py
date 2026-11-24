"""Page nodes keep content deterministic and reserve provider calls for layouts."""

import asyncio

from langgraph.types import interrupt
from langgraph.errors import GraphBubbleUp
from pydantic import ValidationError

from bookgen.adapters.llm.context import provider_context
from bookgen.domain.fallback import safe_fallback_builder
from bookgen.domain.profiler import profile_content
from bookgen.domain.grouping import derive_spans, deterministic_grouping, reconstruct_blocks, validate_grouping
from bookgen.domain.validator import deterministic_validator
from bookgen.domain.compliance import compliance_metrics_scan, mask_blocks, mask_payload, rehydrate_layout
from bookgen.schemas import AtomicTextBlock, BookContext, ImageAssetMeta, MetricEntry, PageGenerationResult, ValidationIssue


class PageNodes:
    def __init__(self, *, provider, repository, storage, settings):
        self.provider = provider
        self.repository = repository
        self.storage = storage
        self.settings = settings

    def profile(self, state):
        profile = profile_content(state["text"], storage=self.storage, settings=self.settings.profiling)
        return {"blocks": [block.model_dump(mode="json") for block in profile.blocks],
                "profile_issues": [issue.model_dump(mode="json") for issue in profile.issues],
                "repair_attempts": 0, "used_fallback": False, "selection": "",
                "source_spans": [], "source_grouping": None, "grouping_used_fallback": False}

    @staticmethod
    def _sources(state):
        return ([AtomicTextBlock.model_validate(block) for block in state["blocks"]],
                [ImageAssetMeta.model_validate(asset) for asset in state["assets"]])

    def compliance_metrics_scan(self, state):
        blocks, _ = self._sources(state)
        ledger = compliance_metrics_scan(blocks, config=self.settings.compliance)
        return {'metrics_ledger': [metric.model_dump(mode='json') for metric in ledger]}

    async def group_spans(self, state):
        blocks, _ = self._sources(state)
        metrics = self._metrics(state)
        config = self.settings.profiling.grouping
        spans = derive_spans(state['text'], blocks, config=config, ledger=metrics)
        fallback = deterministic_grouping(spans)
        used_fallback = False
        # Limits bound grouping requests; oversize input stays on the local path.
        if not spans or len(spans) > config.max_spans or len(state['text']) > config.max_input_chars:
            grouping, used_fallback = fallback, True
        else:
            provider_spans = spans
            if self.settings.compliance.strict_privacy:
                # Mask by exact source occurrence before exposing span text.
                from bookgen.domain.compliance import _metric_spans, _placeholder
                from bookgen.schemas import MetricClassification
                masked = []
                by_id = {block.block_id: block for block in blocks}
                origins = {}
                for span in spans:
                    origins.setdefault(span.source_block_id, span.start)
                for span in spans:
                    block = by_id[span.source_block_id]
                    source = span.text
                    for start, end, metric in sorted(_metric_spans(block, [m for m in metrics
                            if m.source_block_id == block.block_id and m.classification != MetricClassification.PUBLIC]), reverse=True, key=lambda item: item[0]):
                        start += origins[span.source_block_id] - span.start
                        end += origins[span.source_block_id] - span.start
                        if 0 <= start < end <= len(span.text):
                            source = source[:start] + _placeholder(metric) + source[end:]
                    masked.append(span.model_copy(update={'text': source}))
                provider_spans = masked
            try:
                grouping = validate_grouping(await self.provider.group_spans(spans=provider_spans), spans)
            except GraphBubbleUp:
                # Manual grouping uses the same durable dynamic interrupt.
                raise
            except Exception:
                # Grouping is optional enrichment. Unusable output or transport
                # failure retains the deterministic source partition.
                grouping, used_fallback = fallback, True
        grouped = reconstruct_blocks(state['text'], spans, grouping, blocks, metrics,
            word_pattern=self.settings.profiling.block_patterns.word)
        ledger = compliance_metrics_scan(grouped, config=self.settings.compliance)
        return {'source_spans': [span.model_dump(mode='json') for span in spans],
            'source_grouping': grouping.model_dump(mode='json'), 'grouping_used_fallback': used_fallback,
            'blocks': [block.model_dump(mode='json') for block in grouped],
            'metrics_ledger': [metric.model_dump(mode='json') for metric in ledger]}

    def _metrics(self, state):
        return [MetricEntry.model_validate(metric) for metric in state['metrics_ledger']]

    def _validate(self, state, options):
        blocks, assets = self._sources(state)
        return deterministic_validator(options, blocks, assets, state['rolling_layout_history'],
            grammar=self.settings.grammar, metrics=self._metrics(state),
            audience_mode=BookContext.model_validate(state['context']).audience_mode,
            compliance=self.settings.compliance)

    async def _candidate(self, state, index, repair=False):
        blocks, assets = self._sources(state)
        metrics = self._metrics(state)
        private = self.settings.compliance.strict_privacy
        provider_blocks = mask_blocks(blocks, metrics) if private else blocks
        option_id = "option_a" if index == 0 else "option_b"
        context = mask_payload(state['context'], metrics) if private else state['context']
        provider_assets = [ImageAssetMeta.model_validate(mask_payload(asset.model_dump(mode='json'), metrics)) for asset in assets] if private else assets
        kwargs = dict(context=BookContext.model_validate(context), blocks=provider_blocks, assets=provider_assets,
                      strategy_tag=self.settings.llm.strategy_families[option_id])
        with provider_context(page_number=state["page_number"], rhythm_history=tuple(state["rhythm_history"]),
                              recent_archetypes=tuple(state["rolling_layout_history"])):
            try:
                if repair and hasattr(self.provider, "repair_candidate"):
                    candidate = state['options'][index]
                    issues = state['validation_issues']
                    if private:
                        candidate, issues = mask_payload(candidate, metrics), mask_payload(issues, metrics)
                    kwargs.update(candidate=candidate, issues=[ValidationIssue.model_validate(issue) for issue in issues])
                    result = await self.provider.repair_candidate(**kwargs)
                else:
                    result = await self.provider.generate_candidate(**kwargs)
                raw = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
                return rehydrate_layout(raw, blocks, metrics) if isinstance(raw, dict) else raw
            except (ValidationError, ValueError) as exc:
                # Keep malformed structured output in the deterministic repair path.
                return {"option_id": option_id, "invalid_response": str(exc)}

    async def generate_candidates(self, state):
        if state.get("debug_mode"):
            # Ordered interrupts have stable resume positions across node replay.
            return {"options": [await self._candidate(state, 0), await self._candidate(state, 1)]}
        return {"options": list(await asyncio.gather(self._candidate(state, 0), self._candidate(state, 1)))}

    def validate(self, state):
        issues = self._validate(state, state['options'])
        return {"validation_issues": [issue.model_dump(mode="json") for issue in issues]}

    async def repair(self, state):
        if state.get("debug_mode"):
            return {"options": [await self._candidate(state, 0, repair=True), await self._candidate(state, 1, repair=True)],
                    "repair_attempts": state["repair_attempts"] + 1}
        return {"options": list(await asyncio.gather(self._candidate(state, 0, repair=True), self._candidate(state, 1, repair=True))),
                "repair_attempts": state["repair_attempts"] + 1}

    def fallback(self, state):
        blocks, assets = self._sources(state)
        options = safe_fallback_builder(blocks, assets, state["rolling_layout_history"], grammar=self.settings.grammar)
        issues = self._validate(state, options)
        if any(issue.severity == "error" for issue in issues):
            raise ValueError("Fallback failed deterministic validation")
        return {"options": [option.model_dump(mode="json") for option in options], "validation_issues": [], "used_fallback": True}

    def build_review(self, state):
        page = PageGenerationResult(page_id=state["page_id"], page_number=state["page_number"],
            input_blocks=state["blocks"], input_assets=state["assets"], metrics_ledger=state['metrics_ledger'],
            option_a=state["options"][0], option_b=state["options"][1],
            validation_issues=state["profile_issues"], repair_attempts=state["repair_attempts"], used_fallback=state["used_fallback"])
        return {"result": page.model_dump(mode="json")}

    def human_review_interrupt(self, state):
        selection = interrupt({"event": "review", "page": state["result"]})
        if selection not in ("option_a", "option_b"):
            raise ValueError("Invalid selection")
        return {"selection": selection}

    def commit_page(self, state):
        page = PageGenerationResult.model_validate(state["result"]).model_copy(update={"selected_option_id": state["selection"]})
        self.repository.save_snapshot(state["session_id"], page)
        summaries = []
        for snapshot in self.repository.load_snapshots(state["session_id"])[-self.settings.llm.rhythm_window:]:
            selected = getattr(snapshot, snapshot.selected_option_id)
            summaries.append({"page_num": snapshot.page_number, "archetype": selected.archetype.value,
                "density_class": selected.density_scale,
                "has_callout": any(component.component_type.value in ("pull_quote", "stat_callout") for component in selected.components)})
        return {"result": page.model_dump(mode="json"), "current_page_index": page.page_number + 1,
                "rolling_layout_history": [entry["archetype"] for entry in summaries], "rhythm_history": summaries}

    def after_validation(self, state):
        if not any(issue["severity"] == "error" for issue in state["validation_issues"]):
            return "build_review"
        if state["repair_attempts"] < self.settings.llm.max_repair_retries:
            return "repair"
        return "fallback"
