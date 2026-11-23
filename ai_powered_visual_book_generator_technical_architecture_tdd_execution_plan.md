# AI-Powered Visual Book Generator: Technical Architecture & TDD Execution Plan

> **Document Purpose:** Canonical technical specification, Architecture Decision Record (ADR) log, data contract reference, and Test-Driven Development (TDD) execution plan. This document is structured to serve as the primary context source for human engineers and agentic coding assistants so every phase—from MVP demo to 500-page enterprise production—is built iteratively without rewrites.
>
> **Source Alignment:** Derived from `Product Summary_ AI-Powered Visual Book Generator.pdf` (PRD) and finalized architectural trade-off discussions.

---

## 1. Executive Summary & Problem Statement

### 1.1 Business Problem (PRD Sec. 1–3)
Internal marketing and content teams regularly produce large, content-heavy publications (up to **500 pages**). Converting raw text, photography, and data visualizations into visually polished book drafts currently requires heavy manual designer effort, multiple review cycles, and long turnaround times.

### 1.2 Product Objective
Build a browser-based, AI-powered typesetting platform that transforms raw page inputs (text + images) and optional book-level context into a visually cohesive, print-ready book draft. For every page, the system generates **two distinct, context-aware layout options**; the user selects the preferred layout and advances page-by-page (or reviews batches in later phases) until the book draft is complete.

### 1.3 Core Architectural Tension & Resolution
Two PRD success criteria create a deliberate engineering tension:
1. **"Produces visually reasonable and readable pages"** -> demands strict mathematical determinism, typography hygiene, and zero text/image overflow.
2. **"Demonstrates context-aware layout decisions (not just static templates)"** -> demands semantic understanding of text, visual understanding of images, tonal alignment with the book objective, and cross-page visual rhythm.

**Our Core Architectural Thesis:**
We resolve this tension through a **Constrained Design Grammar + Pointer-Based Layout AST**.
* The **AI Orchestration Engine** acts as an *Art Director*, making semantic and structural routing decisions (choosing grid archetypes, visual hierarchy, callout promotions, and image placements) within a strictly typed JSON schema.
* The **Deterministic Rendering & Validation Engine** acts as the *Typesetter*, enforcing fixed physical page dimensions, a 12-column CSS Grid, locked brand design tokens, zero-mutation text hydration, chart-crop protection, and DOM-level overflow guarantees.

### 1.4 PRD Success Criteria Mapped to Engineering KPIs

| PRD Success Criterion | Engineering KPI / Gate | Target |
| :--- | :--- | :--- |
| Significantly faster than manual typesetting | Median page generation latency (Option A + B parallel) | `< 6 seconds` (p95 `< 10s`) |
| Visually reasonable and readable pages | Zero-overflow rate (after deterministic auto-heal) | `100%` |
| Visually reasonable and readable pages | Text/Image drop or hallucination rate | `0%` (strict pointer assertion) |
| Context-aware (not static templates) | Consecutive duplicate archetype rate across a 20-page book | `0%` (sliding exclusion window) |
| Context-aware (not static templates) | Option A vs. Option B structural distinctness score | `100%` different archetype families |
| Handles up to ~500 pages within LLM limits | Token cost & context size per page as page count grows ($N \to 500$) | $O(1)$ constant context per page |

---

## 2. Architectural Research & Decision Records (ADRs)

This section documents all evaluated alternatives, pros/cons trade-offs, and finalized decisions so future contributors and coding agents do not revisit settled boundaries.

### ADR-001: Core Application Stack
* **Options Evaluated:**
  1. *Pure Client-Side (Vite + React + TS + Browser Gemini SDK):* Zero backend DevOps, fast PoC, native DOM math. **Rejected as foundation** because moving to 500-page bulk uploads, server-side PDF rendering, compliance scanning, and durable checkpoints would require a full backend rewrite.
  2. *Pure Python (LangGraph + Streamlit / Gradio):* Single runtime, strong AI orchestration. **Rejected** because Streamlit/Gradio cannot support precision desktop publishing grids, live DOM overflow measurement, or polished split-screen book editing without fragile raw HTML hacks.
  3. *Unified TypeScript (Next.js + Mastra + Vercel AI SDK):* Single language and shared Zod schemas end-to-end. **Strong alternative**, but weaker Python ecosystem for Phase 4 bulk enterprise document parsing (`.docx`, `.pdf`, `.pptx` via `Docling`/`PyMuPDF`/`Pillow`) and slightly less enterprise familiarity than LangGraph.
  4. *Google AI Studio Build Mode:* Fastest 1-day clickable sandbox. **Rejected** for production-extensible foundation due to prototyping sandbox limits.
  5. **SELECTED — Option A: React/Next.js (TypeScript + Tailwind CSS) Frontend + Python (FastAPI + LangGraph) Backend.**
* **Rationale:** Separates the *Visual Rendering Engine* (browser CSS Grid + React) from the *Stateful AI Orchestration Brain* (Python LangGraph) via a strict versioned JSON Layout AST. Gives best-in-class enterprise HITL checkpointing (`StateGraph`, `interrupt()`), parallel map-reduce (`Send()`), and native Python tooling for image inspection (`Pillow`), PDF merging (`pypdf`/`pikepdf`), PII/metrics scanning (`Presidio`), and future 500-page document ingestion (`Docling`).
* **Local Dev Ergonomics:** Runs locally with zero cloud DevOps using **SQLite** (LangGraph checkpointer + app DB) and **local filesystem storage** via adapter interfaces that swap cleanly to PostgreSQL and GCS/S3 in production.

### ADR-002: Deployment & Hosting Topology
* **Decision:** Host the **Next.js/React frontend on Vercel** (giving an edge-cached, snappy client-side editing experience) and deploy the **FastAPI + LangGraph + Playwright backend as a container on Google Cloud Run** (or local Docker Compose during demos).
* **Trade-Off Rationale:** Serverless functions (e.g., Vercel Functions) fight heavy ~300–500 MB Chromium binaries, long-running 500-page batch jobs, and persistent worker pools. Cloud Run provides container-native memory isolation, up to 60-minute request timeouts, scale-to-zero cost efficiency, and native IAM integration for Vertex AI.

### ADR-003: LLM Provider Strategy & Integration
* **Decision:** Use the official **`google-genai`** Python SDK wrapped behind an internal `LLMProvider` interface.
  * **Default Interactive Model:** `gemini-3.8-flash` (low latency, native multimodal vision for images/charts, strict JSON Structured Outputs).
  * **Escalation / Eval Model:** `gemini-3.1-pro` (used for offline VLM-as-a-Judge visual evals and optional complex layout repair).
  * **Performance Optimization:** Enable **Prompt Caching** on the static prefix (System Instructions + Design Grammar Spec + Book Design Tokens) to slash input latency and token costs across 500-page runs.
  * **Environment Switching:** Config-driven toggle between Gemini Developer API key (local dev / Google AI Pro included API credits) and **Vertex AI** (enterprise production with Zero Data Retention).

### ADR-004: Anti-Hallucination & Layout Representation (Pointer-Based AST)
* **Options Evaluated:**
  * *Raw HTML/CSS Generation:* High visual drift, broken print margins, unpredictable overflow, risk of LLM silently altering or omitting copy. **Rejected.**
  * *Rigid Fixed Templates (e.g., 5 hardcoded slots):* Reliable, but fails the PRD "context-aware, not static templates" criterion. **Rejected.**
  * **SELECTED — Constrained Design Grammar + Pointer-Based Layout AST.**
* **Anti-Hallucination Invariants:**
  1. **Zero Text Mutation:** Before invoking the LLM, raw page text is deterministically parsed into indexed atomic blocks (`p_01`, `p_02`, `list_01`, `h_01`) and images into asset IDs (`img_01`). The LLM outputs a layout AST referencing **IDs only**—never re-emitting body copy. The renderer hydrates exact user source strings.
  2. **Extractive-Only Callouts:** If the LLM promotes a pull quote or stat callout, it must supply the source `block_id` and an exact substring verified via deterministic check (`assert excerpt in source_blocks[block_id].text`).
  3. **100% Completeness Gate:** Deterministic validator asserts `set(input_block_ids) == set(placed_block_ids)` and `set(input_image_ids) == set(placed_image_ids)`. Zero silent drops allowed.

### ADR-005: PDF Export Engine & HTML-to-PDF Drift Control
* **Options Evaluated:**
  * *Client-Side (`window.print`, `html2canvas` + `jsPDF`, `Paged.js`):* Rasterized blurry/non-searchable PDFs (`html2canvas`), OS dialog inconsistencies (`window.print`), and browser OOM crashes at 500 pages. **Rejected for full book export** (keep `@media print` only as an instant single-page preview utility).
  * *Dual Rendering Stack (`Typst` / `WeasyPrint`):* Extremely fast compilation, but maintaining two layout engines (React/Tailwind in browser vs. Typst/WeasyPrint for PDF) guarantees visual drift. **Rejected.**
  * **SELECTED — Backend Headless Chromium (Playwright) in a Chunked Map-Merge Pipeline.**
* **Architecture & Drift Controls:**
  1. Render chunks of **10–25 pages** in isolated Playwright browser contexts concurrently to bound memory usage, then merge chunks and inject clickable PDF bookmarks/metadata using `pypdf`/`pikepdf`.
  2. **Structural Drift Prevention:** Bundle exact `.woff2` web fonts inside both frontend and container; enforce explicit physical CSS units (`210mm x 297mm` A4 or US Letter); require `document.fonts.ready` and eager image loading before `page.pdf()`; maintain a 5–8% vertical safety buffer.
  3. **Automated Post-Export PDF Gate:** Assert in Playwright that `scrollHeight <= clientHeight` per page container; post-render, verify via `pypdf` that `physical_pdf_page_count == expected_logical_page_count` (catches OS font-hinting 1-line spillovers immediately).

### ADR-006: Context-Aware Parallelism Without Visual Repetition
* **Problem:** Sequential LLM generation is too slow for bulk 500-page runs, while naive parallel generation causes adjacent pages to pick identical layouts.
* **Decision:**
  * **Interactive Mode (MVP):** Generate Option A and Option B in **parallel** per page (halving latency) using two distinct editorial strategy directives, while passing a **Rolling Exclusion Window** of the last 3–5 selected page archetypes.
  * **Bulk Mode (Phase 4):** **Two-Phase Planner-Worker Graph** using LangGraph's `Send()` fan-out API:
    1. *Phase 1 (Fast Sequential Rhythm Planner):* Inspects a lightweight metadata manifest (word counts, image counts/ratios, chapter markers) for a 10–20 page batch and assigns non-overlapping allowed archetype sets per page.
    2. *Phase 2 (Parallel Workers):* Fans out page generation concurrently within those pre-de-duplicated archetype constraints.

### ADR-007: Global Style Consistency, Brand Extraction & Master Chrome
* **Global Style Consistency:** Book creation locks a single immutable `DesignTokens` JSON object mapped to CSS Custom Properties (`--brand-primary`, `--brand-accent`, `--surface-tint`, `--font-heading`, `--font-body`, `--radius-base`, `--page-margin`). The LLM only selects **semantic style roles** (never raw hex codes or pixel sizes).
* **Website Theme Extraction + Manual Override (Phase 2):** Optional input of a company website URL fetched server-side with **SSRF protection** (blocking private/loopback/metadata IP ranges). Extracts `<meta name="theme-color">`, CSS variables, and dominant header/logo colors, passes them through a **WCAG AA Contrast Sanitizer**, and presents editable color swatches + curated editorial presets before Page 1 generation.
* **Global Headers & Footers (`MasterChromeConfig`):** Optional book-level master template (Left / Center / Right slots supporting static text like copyright notices and dynamic variables `{page_number}`, `{total_pages}`, `{chapter_title}`). Carves out a fixed reserved safe zone (`12mm` top/bottom) outside the AI layout grid and auto-suppresses chrome on `cover`, `section_divider`, and `full_bleed_hero` pages.

### ADR-008: Metrics Isolation & Compliance / Data Security (Phase 2)
* **Problem:** Marketing drafts often contain internal KPIs, draft projections, or `[CONFIDENTIAL]` / `[UNDISCLOSED]` metrics that must never be accidentally elevated into a giant hero `StatCallout` in a client-facing book.
* **Decision:** Integrate a deterministic **Compliance & Metrics Isolation Node** inside content profiling:
  1. Extract numeric claims (`$`, `%`, YoY, ARR, headcount) and sensitivity tags (`[INTERNAL]`, `[CONFIDENTIAL]`, `[UNDISCLOSED]`, `[DRAFT]`) via Regex + NER (`Presidio`).
  2. Maintain a typed `MetricsLedger` (`public` | `internal` | `undisclosed` | `unverified`) evaluated against book `AudienceMode` (`internal` vs. `client_facing`).
  3. **Hard Guardrail:** Any non-`public` metric in `client_facing` mode is strictly barred from `StatCallout` promotion, optionally masked as `[METRIC_01]` before external LLM calls (strict privacy mode), and triggers a mandatory UI compliance sign-off/redaction gate prior to PDF export.

### ADR-009: Pre-Export Structural Assembly (Phase 2)
* **Decision:** Decouple structural book elements from the body-page loop using a 3-section book model:
  * `front_matter[]`: Cover Page, Legal/Imprint, Preface, and auto-generated **Table of Contents (ToC)**.
  * `body_pages[]`: User-created pages + optional auto-inserted `SectionDivider` pages based on chapter tags.
  * `back_matter[]`: Appendix / Closing Cover.
* **Why Pre-Export?** Final page numbering is only stable after body pages are added, reordered, or deleted. Generating the ToC deterministically at assembly time enables accurate page numbers and clickable internal HTML anchors (`#page-N`) preserved by Playwright in the exported PDF.

### ADR-010: Session-Based Generation & Checkpointing
* **Decision:** Every book project is a durable **Session** backed by LangGraph's `thread_id` checkpointer + versioned page snapshots. Supports pause/resume across days, page revisit/re-generation, theme branching, and deterministic state replay for debugging.

---

## 3. Target System Architecture & LangGraph Topology

### 3.1 High-Level Component Architecture

```text
+-----------------------------------------------------------------------------+
|                         FRONTEND (Next.js + React + Tailwind)               |
|  [Book Setup & Theme Swatches]  [Page Composer]  [Side-by-Side A/B Preview] |
|  [Virtualized 500-Page Rail]    [DOM Overflow Probe]   [Compliance Gate UI] |
+--------------------------------------+--------------------------------------+
                                       | REST + SSE Streaming (OpenAPI Typed)
                                       v
+-----------------------------------------------------------------------------+
|                        BACKEND API (FastAPI + Pydantic v2)                  |
|   [Session Controller]  [Asset Upload & Thumbnails]  [Theme Extractor]      |
+-------------------+--------------------------------------+------------------+
                    |                                      |
                    v                                      v
+-------------------------------------------+   +-----------------------------+
|      LANGGRAPH ORCHESTRATOR ENGINE        |   |   CHUNKED PDF EXPORTER      |
|  Checkpointer: SQLite (dev) / PG (prod)   |   |  (Playwright Context Pool)  |
|                                           |   |  10-25 pg chunks -> pypdf   |
|  [1. profile_content (0 LLM)]             |   |  merge -> PDF Drift Gate    |
|        |                                  |   +-----------------------------+
|        v                                  |
|  [2. compliance_metrics_scan (0 LLM)]     |   +-----------------------------+
|        |                                  |   |   INFRA & ADAPTER LAYER     |
|        +--> (Parallel Fan-Out) --------+  |   |  - StorageAdapter (FS/GCS)  |
|        v                               v  |   |  - LLMProvider (Gemini)     |
|  [3a. gen_option_A]       [3b. gen_option_B]  |  - ConfigLoader (YAML+Env)  |
|        |                               |  |   |  - Telemetry (Langfuse/OTel)|
|        +-----------> Join <------------+  |   +-----------------------------+
|                        |                  |
|                        v                  |
|  [4. deterministic_validator (<10ms)]     |
|        |                                  |
|        +-- (PASS) ---------------------+  |
|        |                               |  |
|        +-- (FAIL & retries < 2) ----+  |  |
|        |                            v  |  |
|        |          [5. critic_and_repair]|  |
|        |                   |            |  |
|        |                   +--(loop)----+  |
|        +-- (FAIL & retries == 2) -> [6. safe_fallback_builder]
|                                         |  |
|                                         v  |
|                     [7. human_review_interrupt (HITL)]
|                                         | (User selects A or B / Edits)
|                                         v
|                     [8. commit_page & update_rolling_memory]
+-------------------------------------------+
```

### 3.2 Hierarchical Context Management (Solving the 500-Page Limit)
To keep LLM token usage and latency $O(1)$ regardless of whether the user is on Page 2 or Page 498, **never pass full book history into the prompt**. Each worker node receives strictly three bounded slices:
1. **Global Book Context (~300 tokens, Prompt-Cached):** Book title, objective/tone, audience mode, `DesignTokens` role manifest, and allowed `LayoutArchetype` rules.
2. **Sliding Rhythm Window (~150 tokens):** Compact summary of the last **3–5 committed pages** (`[{page_num, archetype, density_class, has_callout}]`) plus an explicit `excluded_archetypes` list.
3. **Current Page Payload (~500–1,500 tokens):** Indexed atomic text blocks (`block_id`, `type`, `word_count`, `text`), downscaled image thumbnails (max `768px` longest edge to minimize vision token cost while retaining full-res assets in storage), image aspect ratios, and asset types (`photo` vs `chart`).

### 3.3 LangGraph Node Responsibilities

| Node | Execution Type | Responsibility |
| :--- | :--- | :--- |
| `profile_content` | Deterministic Python | Splits raw text into indexed atomic blocks; computes word/character counts; extracts image pixel dimensions, aspect ratios, DPI (`Pillow`), and classifies `photo` vs `chart`. |
| `compliance_metrics_scan` | Deterministic Python | Extracts numeric claims and sensitivity tags; updates `MetricsLedger`; flags restricted metrics so they cannot be promoted to `StatCallout`. |
| `generate_candidates` | Parallel LLM (`asyncio` / LangGraph fan-out) | Runs two concurrent structured-output calls: **Option A** (*Editorial / Visual-First*) and **Option B** (*Executive / Structured-First*), enforcing distinct archetype subsets. |
| `deterministic_validator` | Deterministic Python | Runs fast (<10ms) invariants: schema check, 100% block/image ID completeness, extractive quote verification, chart crop-ban (`object-contain`), slot character-budget estimation, and A vs. B distinctness check. |
| `critic_and_repair` | Conditional LLM (Max 2 loops) | Invoked **only** when `deterministic_validator` fails. Receives exact structured error traces (e.g., `"Option B omitted img_02 and exceeded slot_main budget by 18%"`) and emits a repaired AST. |
| `safe_fallback_builder` | Deterministic Python | Zero-failure safety net if retries exhaust: deterministically places all blocks and images into a guaranteed-readable multi-column fallback layout so the user is never blocked. |
| `human_review_interrupt` | LangGraph `interrupt()` | Persists state to checkpointer, streams Option A + B JSON ASTs + rationales to the frontend, and suspends execution until the user picks an option (or triggers a Phase 3 natural-language refinement). |
| `commit_page` | Deterministic Python | Saves the chosen `PageLayoutAST` snapshot, appends its archetype to `rolling_layout_history`, and increments `current_page_index`. |

---

## 4. Core Data Contracts & Schemas (Agentic Coding Reference)

> **Single Source of Truth Rule:** All schemas are authored in Python (`packages/contracts` or `apps/api/schemas`) using **Pydantic v2** with `extra="forbid"`. A build script exports OpenAPI / JSON Schema and auto-generates TypeScript interfaces for `apps/web` (`openapi-typescript`). Never manually duplicate types across Python and TypeScript.

### 4.1 Enumerations & Constrained Design Grammar

```python
from enum import Enum

class AudienceMode(str, Enum):
    INTERNAL = "internal"
    CLIENT_FACING = "client_facing"

class PageSize(str, Enum):
    A4 = "A4"           # 210mm x 297mm
    US_LETTER = "LETTER" # 215.9mm x 279.4mm

class AssetKind(str, Enum):
    PHOTO = "photo"         # Croppable (object-cover allowed, scrim overlay allowed)
    CHART = "chart"         # NEVER crop (object-contain mandatory, no text overlay)
    DIAGRAM = "diagram"     # NEVER crop (object-contain mandatory, no text overlay)
    LOGO = "logo"

class MetricClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    UNDISCLOSED = "undisclosed"
    UNVERIFIED = "unverified"

class LayoutArchetype(str, Enum):
    # High-impact / low-density
    FULL_BLEED_HERO = "full_bleed_hero"           # Cover / opener with dark scrim
    MINIMALIST_SWISS = "minimalist_swiss"         # Bold type, accent rule, high whitespace
    SECTION_DIVIDER = "section_divider"           # Chapter break
    # Balanced editorial / photo + prose
    EDITORIAL_ASYMMETRIC = "editorial_asymmetric" # 7/5 or 5/7 split + pull quote
    TWO_COL_EXECUTIVE = "two_col_executive"       # Clean 2-col prose + framed media
    TOP_MEDIA_NARRATIVE = "top_media_narrative"   # Wide top visual + structured columns below
    # Data & chart heavy
    CHART_FOCUS_BAND = "chart_focus_band"         # Full-width protected chart + synthesis below
    GUIDED_ALTERNATING = "guided_alternating"     # Left/right paired visual + paragraph rows
    DASHBOARD_SPLIT = "dashboard_split"           # Side-by-side charts + takeaway strip
    # Structured / fallback
    MODULAR_CARDS = "modular_cards"               # Multi-point list / comparison grid
    SAFE_FLOW_FALLBACK = "safe_flow_fallback"     # Deterministic zero-overflow fallback

class SurfaceRole(str, Enum):
    PAPER = "paper"               # Clean page background
    SURFACE_TINT = "surface_tint" # Subtle 4-8% tint of brand primary
    BRAND_DARK = "brand_dark"     # High-contrast dark brand panel
    ACCENT_SOFT = "accent_soft"   # Soft highlight callout surface

class ComponentType(str, Enum):
    HEADING = "heading"
    BODY_PROSE = "body_prose"
    BULLET_LIST = "bullet_list"
    IMAGE_FRAME = "image_frame"
    PULL_QUOTE = "pull_quote"     # Extractive substring only
    STAT_CALLOUT = "stat_callout" # Public/approved metrics only
    CAPTION = "caption"
    DIVIDER_RULE = "divider_rule"
```

### 4.2 Book Session, Design Tokens & Master Chrome

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class DesignTokens(StrictModel):
    theme_id: str
    palette_source: str = Field(description="preset | manual | website_extracted")
    color_paper: str = "#FFFFFF"
    color_ink_primary: str = "#111827"
    color_ink_muted: str = "#4B5563"
    color_brand_primary: str = "#1D4ED8"
    color_brand_accent: str = "#0EA5E9"
    color_surface_tint: str = "#F3F4F6"
    font_heading: str = "Inter"
    font_body: str = "Source Serif 4"
    radius_px: int = Field(default=6, ge=0, le=24)
    page_margin_mm: float = Field(default=16.0, ge=10.0, le=30.0)
    chrome_band_mm: float = Field(default=12.0, ge=0.0, le=20.0)

class MasterChromeConfig(StrictModel):
    enabled: bool = True
    header_left: str = ""
    header_right: str = "{chapter_title}"
    footer_left: str = ""                 # e.g., "(c) 2026 Company Name"
    footer_center: str = ""
    footer_right: str = "Page {page_number} of {total_pages}"
    suppress_on_archetypes: list[LayoutArchetype] = Field(
        default_factory=lambda: [
            LayoutArchetype.FULL_BLEED_HERO,
            LayoutArchetype.SECTION_DIVIDER,
        ]
    )

class BookContext(StrictModel):
    title: str = ""
    objective: str = ""
    tone_keywords: list[str] = Field(default_factory=list)
    audience_mode: AudienceMode = AudienceMode.INTERNAL
    page_size: PageSize = PageSize.A4
    source_website_url: Optional[str] = None
```

### 4.3 Atomic Inputs & Pointer-Based Page Layout AST

```python
class AtomicTextBlock(StrictModel):
    block_id: str          # e.g., "blk_01"
    kind: str              # "heading" | "paragraph" | "list" | "quote"
    text: str
    word_count: int
    char_count: int

class ImageAssetMeta(StrictModel):
    asset_id: str          # e.g., "img_01"
    storage_key: str       # Local path or GCS URI (full-res)
    thumbnail_key: str     # Downscaled <=768px for LLM vision
    mime_type: str
    width_px: int
    height_px: int
    aspect_ratio: float    # width_px / height_px
    estimated_dpi: Optional[int] = None
    asset_kind: AssetKind = AssetKind.PHOTO
    alt_caption: str = ""

class MetricEntry(StrictModel):
    metric_id: str
    source_block_id: str
    raw_value: str
    context_snippet: str
    classification: MetricClassification
    approved_for_export: bool = False

class PlacedComponent(StrictModel):
    component_id: str
    component_type: ComponentType
    slot_id: str                                # Target grid slot name (e.g., "header", "col_left", "media_main")
    source_block_ids: list[str] = Field(default_factory=list)
    source_asset_id: Optional[str] = None
    extracted_excerpt: Optional[str] = None     # Mandatory exact substring for PULL_QUOTE / STAT_CALLOUT
    object_fit: str = "contain"                 # Validator forces "contain" for CHART / DIAGRAM
    surface_role: SurfaceRole = SurfaceRole.PAPER
    emphasis: bool = False

class PageLayoutAST(StrictModel):
    option_id: str                              # "option_a" | "option_b"
    strategy_tag: str                           # e.g., "editorial_visual" | "executive_structured"
    archetype: LayoutArchetype
    rationale: str = Field(max_length=280)      # 1-sentence explanation shown to user
    surface_role: SurfaceRole = SurfaceRole.PAPER
    density_scale: str = "normal"               # "airy" | "normal" | "compact" (used by DOM overflow heal)
    components: list[PlacedComponent]
    column_count: int = Field(default=1, ge=1, le=3)

class ValidationIssue(StrictModel):
    code: str                                   # e.g., "MISSING_BLOCK_ID", "CHART_CROP_FORBIDDEN"
    severity: str                               # "error" | "warning"
    message: str
    target_option: str

class PageGenerationResult(StrictModel):
    page_id: str
    page_number: int
    input_blocks: list[AtomicTextBlock]
    input_assets: list[ImageAssetMeta]
    metrics_ledger: list[MetricEntry]
    option_a: PageLayoutAST
    option_b: PageLayoutAST
    selected_option_id: Optional[str] = None
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    repair_attempts: int = 0
    used_fallback: bool = False
```

---

## 5. Production-Grade Engineering Standards & Config Decoupling

### 5.1 Repository Structure (Monorepo)

```text
visual-book-generator/
├── ARCHITECTURE_AND_TDD_PLAN.md    # This document (agent context)
├── Makefile                        # Unified dev, test, lint, typegen, export commands
├── docker-compose.yml              # Local full-stack + Playwright container (optional)
├── config/                         # DECOUPLED CONFIGURATION (No magic strings in code)
│   ├── app.default.yaml            # Storage adapters, DB URI, feature flags, CORS
│   ├── models.yaml                 # Model IDs, temps, retries, prompt-cache TTL
│   ├── design_grammar.yaml         # Archetype constraints (word budgets, slots, image rules)
│   ├── compliance.yaml             # Regex patterns, sensitivity tags, audience policies
│   └── prompts/                    # Versioned Jinja2/YAML prompt templates
│       ├── system_art_director.yaml
│       ├── strategy_option_a.yaml
│       ├── strategy_option_b.yaml
│       └── critic_repair.yaml
├── apps/
│   ├── api/                        # Python 3.12+ / FastAPI / LangGraph
│   │   ├── pyproject.toml
│   │   ├── src/bookgen/
│   │   │   ├── main.py             # FastAPI entrypoint + lifespan wiring
│   │   │   ├── config/             # Pydantic-settings + YAML loader
│   │   │   ├── schemas/            # Canonical Pydantic v2 Data Contracts
│   │   │   ├── adapters/           # Protocol interfaces + implementations
│   │   │   │   ├── llm/            # GeminiProvider, MockLLMProvider
│   │   │   │   ├── storage/        # LocalFSStorage, GCSStorage
│   │   │   │   ├── db/             # SQLiteRepo, PostgresRepo
│   │   │   │   └── pdf/            # PlaywrightChunkExporter
│   │   │   ├── domain/             # Pure deterministic business logic (100% unit-testable)
│   │   │   │   ├── profiler.py     # Text parser, Pillow image metrics, chart classifier
│   │   │   │   ├── compliance.py   # Metrics isolation & sensitivity gate
│   │   │   │   ├── validator.py    # Schema, pointer completeness, budget, crop & distinctness checks
│   │   │   │   ├── fallback.py     # Deterministic safe layout builder
│   │   │   │   ├── theme.py        # SSRF-safe URL theme extractor + WCAG contrast sanitizer
│   │   │   │   └── assembler.py    # Front matter, ToC, Section Dividers, numbering
│   │   │   ├── graph/              # LangGraph StateGraph, nodes, edges, checkpointer
│   │   │   ├── routes/             # REST + SSE endpoints
│   │   │   └── telemetry/          # OpenTelemetry + Langfuse hooks
│   │   └── tests/
│   │       ├── unit/               # Pure domain & validator tests
│   │       ├── graph/              # LangGraph execution tests with MockLLMProvider
│   │       ├── integration/        # FastAPI + SQLite + Playwright PDF drift tests
│   │       └── golden/             # 25-30 edge-case page fixtures for offline evals
│   └── web/                        # Next.js (App Router) + React + TypeScript + Tailwind
│       ├── package.json
│       ├── src/
│       │   ├── types/generated.ts  # Auto-generated from FastAPI OpenAPI schema
│       │   ├── config/env.ts       # Typed frontend env config
│       │   ├── engine/             # Deterministic Layout Renderer
│       │   │   ├── PageCanvas.tsx  # Physical A4/Letter container + MasterChrome
│       │   │   ├── archetypes/     # 1 React Grid component per LayoutArchetype
│       │   │   ├── blocks/         # Heading, Prose, ImageFrame, PullQuote, StatCallout
│       │   │   └── useOverflowHeal.ts # DOM scrollHeight <= clientHeight auto-healer
│       │   ├── components/         # Setup wizard, Side-by-Side A/B selector, Virtualized rail
│       │   └── app/                # App Router pages + /print/[sessionId] route for Playwright
│       └── tests/
│           ├── unit/               # Vitest renderer & overflow heal tests
│           └── e2e/                # Playwright visual + export parity tests
└── scripts/
    └── sync_contracts.sh           # Exports OpenAPI JSON -> generates web/src/types/generated.ts
```

### 5.2 Configuration Decoupling Standards (12-Factor)
1. **Zero Hardcoded Constants in Source Code:** Model names (`gemini-3.8-flash`), retry caps (`max_repair_retries: 2`), archetype word budgets (`full_bleed_hero.max_words: 45`), compliance tags, and prompt strings MUST live under `/config`.
2. **Layered Override Precedence:** `config/*.default.yaml` -> environment-specific YAML (`APP_ENV=prod`) -> OS environment variables (`BOOKGEN__LLM__MODEL=...`).
3. **Fail-Fast Boot Validation:** All YAML files are parsed into strict Pydantic config models at application startup; invalid config crashes boot immediately rather than failing mid-generation.
4. **Dependency Injection for Testability:** Every external side effect (LLM calls, file storage, database, HTTP theme fetching, Playwright PDF rendering) is hidden behind a Python `typing.Protocol`. Tests inject deterministic in-memory fakes without monkeypatching internals.

---

## 6. Validation, Quality Assurance, Evals, Analytics & Observability

### 6.1 Multi-Layer Deterministic Validation Pipeline

| Stage | Where It Runs | Invariants Enforced | Action on Failure |
| :--- | :--- | :--- | :--- |
| **1. Pre-Flight Asset Check** | `profile_content` (Backend) | Valid MIME types, positive dimensions, DPI warning if `< 150 DPI`, aspect ratio bounds. | Warning badge in UI; non-blocking unless corrupt file. |
| **2. Compliance & Metrics Gate** | `compliance_metrics_scan` (Backend) | Detect `[INTERNAL]`, `[UNDISCLOSED]`, `[CONFIDENTIAL]`, unverified metrics vs. `AudienceMode`. | Block `StatCallout` promotion; lock PDF export until user signs off/redacts. |
| **3. AST Structural Gate** | `deterministic_validator` (Backend) | Strict Pydantic schema; `input_block_ids == placed_block_ids`; `input_asset_ids == placed_asset_ids`; `extracted_excerpt in source_text`; `object_fit == "contain"` for `chart`/`diagram`; archetype word-budget bounds; Option A archetype != Option B archetype; not in rolling exclusion window. | Route to `critic_and_repair` (max 2 retries) -> else `safe_fallback_builder`. |
| **4. DOM Overflow Guardrail** | `useOverflowHeal` (Frontend & Playwright) | Measure `contentEl.scrollHeight <= contentEl.clientHeight` on fixed physical page canvas. | Deterministically step down `density_scale` (`airy` -> `normal` -> `compact`), then escalate to 2-column safe flow if still overflowing. |
| **5. Post-Export PDF Drift Gate** | `PlaywrightChunkExporter` (Backend) | Verify `pypdf` physical page count == expected logical page count; verify non-empty embedded searchable text per page; CI visual SSIM comparison against browser preview. | Flag drifting page chunk, apply `compact` density bump, re-render chunk once; surface explicit diagnostic if unresolved. |

### 6.2 Offline & Online Evals
* **Golden Dataset (`apps/api/tests/golden/`):** 25–30 curated, realistic marketing page scenarios:
  * Dense 500-word executive prose with 0 images.
  * 1-sentence chapter opener + wide landscape photo.
  * 2 side-by-side financial charts + bulleted insights.
  * Mixed portrait headshot + landscape diagram + pull-quote candidate.
  * Pages containing `[INTERNAL]` and `[UNDISCLOSED]` metrics in `client_facing` mode.
* **Automated Eval Metrics (Run on Prompt/Grammar Changes in CI):**
  * `First-Pass Valid Rate` (target `>= 90%` without needing repair loop).
  * `Hallucination / Drop Rate` (target `0%`).
  * `20-Page Non-Repetition Score` (target `100%` no back-to-back archetype repeats).
  * `VLM-as-a-Judge Visual Score` (Gemini 3.1 Pro grading rendered PNGs on typography hierarchy, whitespace balance, and Option A vs. B distinctness on a 1–5 rubric).

### 6.3 Product Analytics & Observability
* **Analytics Events (Proves PRD Success Criteria):** `session_created`, `page_generated` (latency, token count, repair count, used_fallback), `option_selected` (option_a vs option_b ratio, time-to-decision), `page_regenerated`, `compliance_override`, `book_exported` (page_count, export_duration_ms, drift_gate_passed).
* **Observability Stack:** Instrument LangGraph nodes and FastAPI routes with **OpenTelemetry** exporting traces to **Langfuse** (self-hostable MIT open-source for enterprise data sovereignty). Track per-node latency histograms, token spend per 100 pages, validation failure codes, and Playwright worker RAM utilization.

---

## 7. Decoupled Delivery Roadmap (MVP vs. Phase-Wise Iterations)

Every phase directly maps to `Product Summary_ AI-Powered Visual Book Generator.pdf` while ensuring zero throwaway code between phases.

| Phase | PRD Alignment | Scope Delivered | Architecture Plug-In Mechanism |
| :--- | :--- | :--- | :--- |
| **Phase 0: Foundation** | Engineering Enabler | Monorepo scaffold, decoupled YAML config loader, Pydantic v2 Data Contracts, OpenAPI -> TS typegen, CI test runner, Storage/LLM Protocol adapters (SQLite + LocalFS + MockLLM). | Establishes the versioned AST seam & TDD harness. |
| **Phase 1: Core MVP** | **PRD Sec. 4, 5, 8, 10** (MVP Scope & Deliverables) | Browser studio; optional Book Context (Title, Objective); page-by-page Text + Image upload; LangGraph 5-stage pipeline (`profile -> parallel A/B gen -> deterministic validator -> conditional repair -> HITL interrupt -> commit`); rolling 3-page anti-repetition memory; 8 composable React/Tailwind archetypes; AI Layout Rationale badge; DOM overflow auto-heal; session persistence (SQLite); complete book draft viewer + basic browser print view. | Delivers 100% of PRD MVP + deterministic quality gates, ready for local demo or Vercel/Cloud Run deploy. |
| **Phase 2: Production Publishing & Compliance** | Enterprise Readiness & Quality Hardening | Backend chunked **Playwright PDF Export** + `pypdf` merge + **PDF Drift Validation Gate**; Website URL theme extraction (SSRF-safe + WCAG sanitizer) & manual brand color pickers; Global `MasterChromeConfig` (optional headers/footers/page numbers); **Metrics Isolation & Compliance Gate**; Pre-Export Assembly (**Cover, Preface, Section Dividers, clickable ToC**). | Adds new deterministic nodes & pre-export assembler around the unchanged Phase 1 `PageLayoutAST`. |
| **Phase 3: Interactive Editing & Themes** | **PRD Sec. 7** (Future Enhancements: NL/UI edits, Save/Revisit, Themes) | Natural-language page editing (*"make image larger and pull out the 3x ROI quote"*) via a `refine_page` LangGraph branch; full page revisit/reorder/time-travel UI; curated multi-theme preset library (live theme swap with zero LLM re-runs); light UI slot-swap controls. | Extends `human_review_interrupt` with an edit loop and swaps `DesignTokens`. |
| **Phase 4: 500-Page Bulk Scale & LLMOps** | **PRD Sec. 7 & 8** (Bulk Upload & ~500-Page Scale) | Bulk `.docx` / `.pdf` / `.pptx` ingestion (`Docling`/`PyMuPDF`) with semantic page chunking; **Two-Phase Planner-Worker** parallel batch generation (LangGraph `Send()` fan-out + async worker queue); **Virtualized 500-page UI rail** (`TanStack Virtual`); PostgreSQL + GCS/S3 adapter activation; Langfuse observability + CI Golden VLM Eval suite. | Activates cloud adapters via config YAML and plugs `chunk_document` + `rhythm_planner` upstream of the existing worker graph. |

---

## 8. Test-Driven Development (TDD) Execution Plan

This section defines the deterministic **Red -> Green -> Refactor** build order for human engineers and agentic coding tools.

### 8.1 TDD Rules for Agentic Coding
1. **Strict Red-First Discipline:** For every task below, create and run the test file FIRST. Confirm the test fails for the expected assertion reason before writing production code.
2. **Deterministic Mocks Only in Unit/Graph Tests:** Never call live Gemini APIs in `tests/unit/` or `tests/graph/`. Use `MockLLMProvider` returning scripted valid and intentionally malformed `PageLayoutAST` fixtures to prove every validation branch and retry cap deterministically.
3. **Contract-First Verification:** Whenever a Pydantic schema changes, run `make sync-contracts` and verify both `pytest` and `tsc --noEmit` pass.
4. **Coverage Gates:** Minimum `90%` branch coverage on `src/bookgen/domain/` (profiler, validator, compliance, fallback, assembler) and `>= 80%` on `src/bookgen/graph/` and `apps/web/src/engine/`.

### 8.2 Sprint-by-Sprint TDD Execution Sequence

#### Sprint 0: Contracts, Config Decoupling & Harness (Phase 0)
* **Write Tests First:**
  * `apps/api/tests/unit/test_config_loader.py`: Verify default YAML loading, env-var override precedence, and fail-fast `ValidationError` on missing/invalid grammar rules.
  * `apps/api/tests/unit/test_schemas.py`: Verify `extra="forbid"` rejects unknown LLM keys, invalid `column_count` fails, and `PageLayoutAST` serializes cleanly to JSON Schema.
* **Implement:** `config/*.yaml`, `src/bookgen/config/`, `src/bookgen/schemas/`, `scripts/sync_contracts.sh`, `Makefile`.
* **Exit Gate:** `pytest apps/api/tests/unit/test_config_loader.py apps/api/tests/unit/test_schemas.py` green; `apps/web/src/types/generated.ts` cleanly generated with `tsc --noEmit` passing.

#### Sprint 1: Pure Deterministic Domain Core — Profiler, Validator & Fallback (Phase 1 Backend Core)
* **Write Tests First:**
  * `apps/api/tests/unit/test_profiler.py`: Test text parsing into stable `blk_XX` atomic blocks (headings, paragraphs, lists), accurate word/char counting, Pillow dimension/aspect-ratio extraction, and chart vs. photo heuristic tagging.
  * `apps/api/tests/unit/test_validator.py`: Write table-driven tests covering every invariant:
    * Fails with `MISSING_BLOCK_ID` if any input block is omitted.
    * Fails with `UNKNOWN_BLOCK_ID` if LLM invents a block ID.
    * Fails with `HALLUCINATED_EXCERPT` if a `PULL_QUOTE` or `STAT_CALLOUT` is not an exact substring of its referenced block.
    * Fails with `CHART_CROP_FORBIDDEN` if `asset_kind == CHART` and `object_fit != "contain"`.
    * Fails with `ARCHETYPE_OVERFLOW_BUDGET` if 400 words are assigned to `FULL_BLEED_HERO`.
    * Fails with `DUPLICATE_STRATEGY` if Option A and Option B pick the same archetype.
    * Fails with `RECENT_ARCHETYPE_REPEAT` if an archetype matches the rolling exclusion window.
  * `apps/api/tests/unit/test_fallback.py`: Assert `safe_fallback_builder` produces a 100%-valid `PageLayoutAST` (passes `deterministic_validator`) for 0 images, 1 portrait, 4 charts, and 800-word dense inputs.
* **Implement:** `src/bookgen/domain/profiler.py`, `validator.py`, `fallback.py`, and `config/design_grammar.yaml`.
* **Exit Gate:** 100% pass on all unit tests; `>= 95%` branch coverage on `domain/`.

#### Sprint 2: LangGraph Orchestrator, Checkpointing & Gemini Adapter (Phase 1 AI Engine)
* **Write Tests First:**
  * `apps/api/tests/graph/test_page_graph.py` (using `MockLLMProvider` + in-memory SQLite checkpointer):
    * **Happy Path:** Parallel Option A & Option B pass validation on attempt 1 -> graph suspends at `human_review_interrupt` -> resuming with `option_a` commits page and appends archetype to `rolling_layout_history`.
    * **Self-Healing Repair Loop:** `MockLLMProvider` omits `blk_02` on attempt 1 -> graph routes to `critic_and_repair` with exact error trace -> attempt 2 succeeds -> `repair_attempts == 1`.
    * **Max-Retry Safe Fallback:** `MockLLMProvider` fails 3 consecutive times -> graph caps retries at config limit (`2`) and routes to `safe_fallback_builder` -> `used_fallback == True`, never crashes.
    * **Session Pause/Resume:** Instantiate a fresh graph instance against the same SQLite `thread_id` and verify state resumes seamlessly at the exact page and rolling history.
  * `apps/api/tests/unit/test_gemini_adapter.py`: Verify structured schema payload assembly, thumbnail base64 attachment, and prompt-cache prefix formatting (mocking SDK transport).
* **Implement:** `src/bookgen/adapters/llm/`, `src/bookgen/adapters/storage/local_fs.py`, `src/bookgen/graph/` (`state.py`, `nodes.py`, `workflow.py`), and `src/bookgen/routes/` (FastAPI REST + SSE).
* **Exit Gate:** All graph & API integration tests pass deterministically with zero live API calls; optional tagged `@pytest.mark.live_llm` smoke test verifies live Gemini 3.8 Flash structured output.

#### Sprint 3: Deterministic Visual Engine & Side-by-Side MVP UI (Phase 1 Frontend)
* **Write Tests First:**
  * `apps/web/tests/unit/PageCanvas.test.tsx` (Vitest + React Testing Library):
    * Verify every `LayoutArchetype` (all 8) renders all hydrated `source_block_ids` verbatim (zero text loss).
    * Verify `CHART` assets strictly render with `object-contain` CSS class and zero text overlays.
    * Verify `DesignTokens` map accurately to CSS Custom Properties on the canvas root.
  * `apps/web/tests/unit/useOverflowHeal.test.ts`: Mock `scrollHeight > clientHeight` and assert deterministic step-down (`airy` -> `normal` -> `compact` -> `SAFE_FLOW_FALLBACK`).
  * `apps/web/tests/e2e/mvp_flow.spec.ts` (Playwright): Create book with title/objective -> input 3 pages with text + images -> assert 2 distinct options + rationales render -> select options using click & keyboard (`1`/`2`/`Enter`) -> refresh browser -> verify session persistence and 3-page book draft view.
* **Implement:** `apps/web/src/engine/` (`PageCanvas`, 8 archetype components, block components, `useOverflowHeal`), book setup form, page composer, side-by-side comparison studio, and book draft viewer.
* **Exit Gate:** Complete **Phase 1 MVP** passing unit, integration, and Playwright E2E tests. Ready for stakeholder demo!

#### Sprint 4: Compliance Gate, Brand Theme Extraction & Master Chrome (Phase 2A)
* **Write Tests First:**
  * `apps/api/tests/unit/test_compliance.py`: Test extraction of `$4.2M ARR`, `42% YoY`, `[INTERNAL]`, `[UNDISCLOSED]` tags; assert validator blocks non-public metrics from `STAT_CALLOUT` in `client_facing` mode; test pre-LLM redaction/re-hydration roundtrip.
  * `apps/api/tests/unit/test_theme_extractor.py`: Test SSRF guardrail (rejects `127.0.0.1`, `169.254.169.254`, `10.0.0.1`); test WCAG AA contrast sanitizer (auto-darkens low-contrast yellow `#FFEE00` on white `#FFFFFF` to `>= 4.5:1` contrast ratio).
  * `apps/web/tests/unit/MasterChrome.test.tsx`: Verify `{page_number}` / `{total_pages}` / copyright footer rendering and automatic suppression on `FULL_BLEED_HERO` and `SECTION_DIVIDER`.
* **Implement:** `domain/compliance.py`, `domain/theme.py`, `MasterChrome` UI/CSS layer, and Compliance Sign-Off banner.
* **Exit Gate:** All compliance, SSRF, and WCAG tests pass; export button remains locked until unapproved internal metrics are resolved.

#### Sprint 5: Pre-Export Assembly & Chunked Playwright PDF Exporter with Drift Gate (Phase 2B)
* **Write Tests First:**
  * `apps/api/tests/unit/test_assembler.py`: Verify deterministic insertion of Cover, Preface, Section Dividers, and clickable ToC with accurate recalculated page numbers after page reordering/deletion.
  * `apps/api/tests/integration/test_pdf_exporter.py`:
    * Render a 12-page mock book through `PlaywrightChunkExporter` (chunk size = 5) -> merge via `pypdf`.
    * Assert `physical_pdf_page_count == 12` (Drift Gate).
    * Assert every page contains searchable embedded text matching input blocks.
    * Inject an intentional overflow stress page and assert the drift gate catches and heals/flags it.
* **Implement:** `domain/assembler.py`, `/print/[sessionId]` Next.js print route (with bundled `.woff2` fonts), and `adapters/pdf/playwright_exporter.py`.
* **Exit Gate:** End-to-end 12-page multi-chunk PDF export succeeds with zero drift and clickable ToC links.

#### Sprint 6: NL Editing, Bulk 500-Page Planner-Worker & Observability (Phases 3 & 4)
* **Write Tests First:**
  * `apps/api/tests/graph/test_refine_branch.py`: Verify natural-language edit (*"swap image to right column"*) patches only the targeted page AST while preserving all block IDs and running the full validator.
  * `apps/api/tests/graph/test_bulk_planner_worker.py`: Feed a 30-page manifest into the Two-Phase Planner-Worker (`Send()` fan-out) and assert: (a) parallel execution completes cleanly, (b) `0%` consecutive duplicate archetypes across all 30 pages, (c) all 30 pages pass completeness invariants.
  * `apps/web/tests/unit/VirtualizedBookRail.test.tsx`: Mount a 500-page session fixture and assert DOM node count stays bounded (`< 30` mounted thumbnail items).
  * `apps/api/tests/golden/test_eval_suite.py`: Run the 25–30 golden edge-case pages against the pipeline and enforce CI regression thresholds.
* **Implement:** `refine_page` graph node, `Docling`/`PyMuPDF` bulk ingestion worker, LangGraph `Send()` batch planner, `TanStack Virtual` sidebar, Postgres/GCS adapters, and Langfuse OpenTelemetry exporter.
* **Exit Gate:** 500-page synthetic stress test passes memory, virtualization, non-repetition, and PDF drift gates.

---

## 9. Agentic Coding Guardrails (Strict Invariants)

Any AI coding assistant implementing tasks from this specification MUST obey these non-negotiable rules:

1. **NEVER allow an LLM to generate raw HTML, raw CSS, hex colors, or pixel margins.** All layouts must be emitted as `PageLayoutAST` validated by Pydantic v2 and rendered via semantic Tailwind/CSS-variable components.
2. **NEVER allow an LLM to rewrite or re-emit user body copy.** Always route via `source_block_ids` pointers; validate any `extracted_excerpt` via exact substring assertion.
3. **NEVER apply `object-cover` cropping or text overlays to `CHART` or `DIAGRAM` assets.** Enforce `object-contain` both in the backend validator and frontend `ImageFrame` component.
4. **NEVER hardcode model identifiers, prompts, word budgets, or compliance regexes in Python/TypeScript logic.** Load all parameters from `/config/*.yaml`.
5. **NEVER mutate Pydantic schemas without running `make sync-contracts`** to regenerate `apps/web/src/types/generated.ts`.
6. **NEVER write production logic before writing and executing the corresponding failing test** for the active sprint task.
7. **NEVER send raw full-resolution images or full 500-page history to the LLM.** Always transmit downscaled thumbnails (`<= 768px`) and the bounded 3-slice hierarchical context.