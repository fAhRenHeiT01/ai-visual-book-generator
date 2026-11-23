# TICKET-19 — Context-aware art direction

**Status:** Open · **Predecessor:** [Ticket 18](TICKET-18.md)

Choose a book direction and generate meaningful page treatments.

## Implementation

- Support brand-led editorial, consulting report, and campaign presentation. Resolve Auto once from the book objective, audience, and tone using YAML-owned rules. Allow an explicit choice before generation. Persist the direction independently of palette and page size.
- Extend `PageLayoutAST` with constrained, named treatments for composition, surface, emphasis, and media placement. Use semantic groups, aspect ratios, budgets, and bounded page history to choose eligible A/B arrangements.
- Apply the same treatment vocabulary to generation, manual prompts, repair, validation, and fallback. Make the deterministic path use headings, lists, and focal elements when the source supports them. Keep raw HTML, CSS, colors and layout measurements out of model output.

## TDD and acceptance

**First failing test.** Run the three visual review fixtures through the offline layout path and assert that source roles and asset constraints influence the selected treatments.

- Cover Auto and all three overrides, legacy book contexts and AST defaults, and distinct A/B hierarchies. The fallback retains every pointer and uses eligible slots.
- Verify excerpt fidelity, restricted callout handling, rolling exclusions, and chart protection on initial and repaired options. Renderer implementation belongs to Ticket 20.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/config/grammar.py`
- `apps/api/src/bookgen/schemas/__init__.py`
- `apps/api/src/bookgen/domain/fallback.py`
- `apps/api/src/bookgen/graph/workflow.py`
- `apps/api/src/bookgen/adapters/llm/gemini.py`
- `apps/api/src/bookgen/adapters/llm/mock.py`
- `apps/api/src/bookgen/graph/nodes.py`
- `apps/api/src/bookgen/domain/direction.py`
- `config/design_grammar.yaml`
- `config/prompts/system_art_director.yaml`
- `apps/api/tests/unit/test_fallback.py`
- `apps/api/tests/unit/test_schemas.py`
- `apps/api/src/bookgen/domain/validator.py`
- `config/prompts/strategy_option_a.yaml`
- `config/prompts/strategy_option_b.yaml`
- `config/prompts/critic_repair.yaml`
- `apps/api/tests/unit/test_validator.py`
- `apps/api/tests/graph/test_page_graph.py`
- `apps/api/openapi.json`
- `apps/web/src/types/generated.ts`
