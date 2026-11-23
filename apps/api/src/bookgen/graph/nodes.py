"""Page nodes keep content deterministic and reserve provider calls for layouts."""

import asyncio

from langgraph.types import interrupt
from pydantic import ValidationError

from bookgen.adapters.llm.context import provider_context
from bookgen.domain.fallback import safe_fallback_builder
from bookgen.domain.profiler import profile_content
from bookgen.domain.validator import deterministic_validator
from bookgen.schemas import AtomicTextBlock, BookContext, ImageAssetMeta, PageGenerationResult, ValidationIssue


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
                "repair_attempts": 0, "used_fallback": False, "selection": ""}

    @staticmethod
    def _sources(state):
        return ([AtomicTextBlock.model_validate(block) for block in state["blocks"]],
                [ImageAssetMeta.model_validate(asset) for asset in state["assets"]])

    async def _candidate(self, state, index, repair=False):
        blocks, assets = self._sources(state)
        option_id = "option_a" if index == 0 else "option_b"
        kwargs = dict(context=BookContext.model_validate(state["context"]), blocks=blocks, assets=assets,
                      strategy_tag=self.settings.llm.strategy_families[option_id])
        with provider_context(page_number=state["page_number"], rhythm_history=tuple(state["rhythm_history"]),
                              recent_archetypes=tuple(state["rolling_layout_history"])):
            try:
                if repair and hasattr(self.provider, "repair_candidate"):
                    kwargs.update(candidate=state["options"][index], issues=[ValidationIssue.model_validate(issue) for issue in state["validation_issues"]])
                    result = await self.provider.repair_candidate(**kwargs)
                else:
                    result = await self.provider.generate_candidate(**kwargs)
                return result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            except (ValidationError, ValueError) as exc:
                # Keep malformed structured output in the deterministic repair path.
                return {"option_id": option_id, "invalid_response": str(exc)}

    async def generate_candidates(self, state):
        return {"options": list(await asyncio.gather(self._candidate(state, 0), self._candidate(state, 1)))}

    def validate(self, state):
        blocks, assets = self._sources(state)
        issues = deterministic_validator(state["options"], blocks, assets, state["rolling_layout_history"], grammar=self.settings.grammar)
        return {"validation_issues": [issue.model_dump(mode="json") for issue in issues]}

    async def repair(self, state):
        return {"options": list(await asyncio.gather(self._candidate(state, 0, repair=True), self._candidate(state, 1, repair=True))),
                "repair_attempts": state["repair_attempts"] + 1}

    def fallback(self, state):
        blocks, assets = self._sources(state)
        options = safe_fallback_builder(blocks, assets, state["rolling_layout_history"], grammar=self.settings.grammar)
        issues = deterministic_validator(options, blocks, assets, state["rolling_layout_history"], grammar=self.settings.grammar)
        if any(issue.severity == "error" for issue in issues):
            raise ValueError("Fallback failed deterministic validation")
        return {"options": [option.model_dump(mode="json") for option in options], "validation_issues": [], "used_fallback": True}

    def build_review(self, state):
        page = PageGenerationResult(page_id=state["page_id"], page_number=state["page_number"],
            input_blocks=state["blocks"], input_assets=state["assets"], metrics_ledger=[],
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
