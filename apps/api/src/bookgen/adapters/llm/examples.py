"""Scripted local fixtures using current grammar, directions and exact pointers."""

from bookgen.adapters.llm.mock import MockLLMProvider
from bookgen.examples import apply_probe
from bookgen.domain.profiler import profile_content


class ExampleLLMProvider(MockLLMProvider):
    """No client, key, network or binary asset reads; only current-page metadata."""

    def __init__(self, *, case, settings):
        super().__init__(settings=settings)
        self.case = case
        self._source_text = "".join(block.text for block in profile_content(
            case["copy"], storage=None, settings=settings.profiling).blocks)

    async def generate_candidate(self, **kwargs):
        page = await super().generate_candidate(**kwargs)
        return self._script(page, kwargs, repair=False)

    async def repair_candidate(self, **kwargs):
        page = await super().repair_candidate(**kwargs)
        return self._script(page, kwargs, repair=True)

    def _script(self, page, kwargs, *, repair):
        outcome = self.case["expected"]["outcome"]
        unchanged = "".join(block.text for block in kwargs["blocks"]) == self._source_text
        if unchanged and page.option_id == "option_a" and (outcome == "fallback" or outcome == "repair" and not repair):
            # User edits retain the local deterministic provider without replaying
            # a source-specific probe against unrelated new content.
            probe = self.case["expected"].get("failure_probe")
            applicable = (probe and (probe["mutation"] != "invent_excerpt" or any(component.extracted_excerpt for component in page.components))
                and (probe["mutation"] != "cover_protected" or any(asset.asset_kind in self.settings.grammar.protected_asset_kinds for asset in kwargs["assets"])))
            if applicable:
                return apply_probe(page, self.case, kwargs["blocks"], kwargs["assets"],
                    protected_kinds=self.settings.grammar.protected_asset_kinds)
        return page
