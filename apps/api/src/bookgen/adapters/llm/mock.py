"""Deterministic injectable provider; never touches external services."""

from collections import defaultdict

from bookgen.config import load_settings
from bookgen.domain.fallback import safe_fallback_builder

from .context import request_context


class MockLLMProvider:
    def __init__(self, *, fail_rounds=0, rendezvous=None, settings=None):
        self.settings = settings or load_settings()
        self.fail_rounds = fail_rounds
        self.rendezvous = rendezvous
        self.calls = []
        self.repairs = []
        self.grouping_calls = []
        self._attempts = defaultdict(int)

    async def group_spans(self, *, spans):
        from bookgen.domain.grouping import deterministic_grouping
        self.grouping_calls.append(spans)
        return deterministic_grouping(spans)

    async def generate_candidate(self, *, context, blocks, assets, strategy_tag):
        if self.rendezvous is not None:
            await self.rendezvous(strategy_tag)
        return self._candidate(context=context, blocks=blocks, assets=assets, strategy_tag=strategy_tag)

    async def repair_candidate(self, *, context, blocks, assets, strategy_tag, candidate, issues):
        self.repairs.append({"candidate": candidate, "issues": issues})
        return self._candidate(context=context, blocks=blocks, assets=assets, strategy_tag=strategy_tag)

    def _candidate(self, *, context, blocks, assets, strategy_tag):
        self.calls.append({"context": context, "blocks": blocks, "assets": assets, "strategy_tag": strategy_tag})
        pair = safe_fallback_builder(blocks, assets, request_context.get().recent_archetypes,
            grammar=self.settings.grammar, context=context, compliance=self.settings.compliance)
        index = int(strategy_tag == self.settings.llm.strategy_families["option_b"])
        page = pair[index].model_copy(update={"strategy_tag": strategy_tag}, deep=True)
        round_number = self._attempts[strategy_tag]
        self._attempts[strategy_tag] += 1
        if round_number < self.fail_rounds:
            page.components = [component for component in page.components if "blk_02" not in component.source_block_ids]
        return page
