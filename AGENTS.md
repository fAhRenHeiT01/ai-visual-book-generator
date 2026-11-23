# AGENTS.md — Visual Book Generator

## 1. Project Overview & Stack
- **Monorepo Layout:**
  - `apps/api`: Python 3.12+, FastAPI, Pydantic v2 (`extra="forbid"`), LangGraph, SQLite (dev) / Postgres (prod), Playwright (`pypdf`).
  - `apps/web`: Next.js (App Router), React, TypeScript (strict), Tailwind CSS, Vitest, Playwright.
  - `config/`: Layered YAML configs (`app.default.yaml`, `models.yaml`, `design_grammar.yaml`, `compliance.yaml`, `prompts/*.yaml`).
- **Canonical Spec:** `ARCHITECTURE_AND_TDD_PLAN.md` (refer to Section 4 for exact Pydantic schemas and Section 8 for TDD gates).

## 2. Build, Typegen & Test Commands
- **Sync OpenAPI -> TS Types:** `make sync-contracts` (exports FastAPI OpenAPI JSON and updates `apps/web/src/types/generated.ts`).
- **Backend Unit & Graph Tests:** `pytest apps/api/tests/unit apps/api/tests/graph`
- **Frontend Unit Tests:** `npm --prefix apps/web run test`
- **Frontend Typecheck:** `npm --prefix apps/web run typecheck` (`tsc --noEmit`)

## 3. Non-Negotiable Architectural Invariants
1. **Constrained Design Grammar Only:** NEVER generate raw HTML, raw CSS, hex colors, or pixel margins from an LLM. All layouts must validate against `PageLayoutAST` and render via semantic Tailwind/CSS-variable components.
2. **Zero Text Mutation (Pointer AST):** NEVER allow an LLM to rewrite or re-emit user body copy. Always reference `source_block_ids`. Any `extracted_excerpt` in `PULL_QUOTE` or `STAT_CALLOUT` must pass exact substring verification (`excerpt in source_blocks[id].text`).
3. **Chart Crop Protection:** NEVER apply `object-cover` or text overlays to `CHART` or `DIAGRAM` assets. Enforce `object-contain` in both `validator.py` and `ImageFrame.tsx`.
4. **Zero Hardcoded Config:** NEVER hardcode model names, retry caps, word budgets, regex patterns, or prompt templates in `.py` or `.ts` files. Load all parameters from `/config/*.yaml` via Pydantic-settings.
5. **Single Source of Truth for Types:** NEVER manually duplicate Pydantic models in TypeScript. Edit `apps/api/src/bookgen/schemas/` and run `make sync-contracts`.
6. **Bounded Context & Assets:** NEVER send full-resolution images (`>768px`) or full multi-page history to LLM providers.

## 4. Strict TDD & Ticket Workflow
- **Red -> Green -> Refactor:** For every ticket, write the failing test file FIRST, run it to confirm the expected failure, then implement the minimal production code to pass.
- **No Live LLM Calls in Tests:** Always inject `MockLLMProvider` in unit and graph tests.
- **File Ownership:** Modify ONLY the files listed in your assigned `/tasks/TICKET-XX.md`. Do not refactor unrelated modules.
- **Exit Criteria:** A ticket is incomplete until all new tests, existing tests, and `tsc --noEmit` pass with zero warnings.
