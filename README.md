# Visual Book Generator

Visual Book Generator turns source text and images into a paginated, illustrated book. The web app provides the authoring and review experience; the FastAPI service manages sessions, layout generation, compliance review, theme settings, and verified PDF export.

## Project status

This repository implements the Phase 0–2 workflow described in [the architecture and TDD plan](ai_powered_visual_book_generator_technical_architecture_tdd_execution_plan.md): session creation, page generation and selection, source-bound compliance decisions, theme and page chrome, deterministic book assembly, and PDF export.

The current persistence adapters use **SQLite and local files**. They are suitable for local development and short-lived previews. Cloud Run’s writable filesystem is instance-local, memory-backed, and does not persist when an instance stops. The Cloud Run recipe below is therefore for a preview or controlled demonstration; it is not a durable production data tier. Before storing customer books, implement and validate durable database and object-storage adapters, backups, authentication, authorization, and tenant isolation. See [Production readiness](#production-readiness).

## Architecture

| Area | Location | Responsibility |
|---|---|---|
| Web | `apps/web` | Next.js App Router UI, semantic page renderer, studio, print route, browser tests |
| API | `apps/api` | FastAPI, Pydantic schemas, LangGraph workflow, SQLite session/checkpoint storage, local assets, compliance and PDF export |
| Runtime configuration | `config` | Layered YAML for models, grammar, compliance, themes, export, and prompts |
| API contract | `apps/api/openapi.json`, `apps/web/src/types/generated.ts` | Generated OpenAPI and TypeScript types |
| CI | `.github/workflows/ci.yml` | Contract validation, Python and web gates, browser-backed checks, coverage |

The browser calls the API directly. For split deployments, configure the web app’s `NEXT_PUBLIC_API_ORIGIN` and allow that exact web origin in the API’s `BOOKGEN__APP__CORS_ORIGINS`. PDF export also loads the web app’s print route; configure `BOOKGEN__EXPORT__PRINT_ORIGIN` to the deployed web origin.

## Prerequisites

- Python 3.12 or newer
- Node.js 22 and npm
- GNU Make and Bash for contract and coverage targets (Git Bash works on Windows)
- Chromium for browser-backed integration and end-to-end tests
- Optional: a Gemini API key, or Google Cloud Application Default Credentials for Vertex AI

## Bootstrap

Use Python 3.12 or newer and Node.js 22. Run these commands from the repository root. On Windows, the Python launcher can select Python 3.12 explicitly with `py -3.12`.

Create and activate the API virtual environment:

```bash
# macOS / Linux
python3.12 -m venv .venv
source .venv/bin/activate
```

```powershell
# Windows PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the API dependencies and the web app's locked dependencies:

```bash
python -m pip install -e "./apps/api[test]"
npm --prefix apps/web ci
```

If PowerShell says script execution is disabled when activating the environment, either allow the activation script for your user or skip activation and invoke `.\.venv\Scripts\python.exe` in place of `python` in the commands below.

Install Chromium for browser-backed checks:

```bash
python -m playwright install chromium
npm --prefix apps/web exec -- playwright install chromium
```

On Linux CI images, Playwright may also need its system packages. The repository’s `make browser` target uses Playwright’s `--with-deps` option to install Chromium and those packages.

## Run locally with your Google AI Studio key

The API uses Gemini by default. A Google AI Studio API key is used through the Google Gen AI SDK's `GEMINI_API_KEY` environment variable. Keep the key in your terminal environment; do not put it in a source file, README, or commit it to Git. The database is `./bookgen.db`, and uploaded assets go in `./uploads`; both are local and ignored by Git.

Start the API first. Open terminal 1 at the repository root, activate `.venv` as shown above, and set the API environment. These variables apply only to that terminal session.

```bash
# macOS / Linux
export PYTHONPATH="$PWD/apps/api/src"
read -s -p "Google AI Studio API key: " GEMINI_API_KEY; export GEMINI_API_KEY; echo
export BOOKGEN__LLM__PROVIDER=gemini
# Optional preflight: sends one small request using the configured model/key.
python -m bookgen.provider_check
python -m uvicorn bookgen.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

```powershell
# Windows PowerShell
$env:PYTHONPATH = (Resolve-Path apps/api/src).Path
$secureKey = Read-Host "Google AI Studio API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
Remove-Variable secureKey
$env:BOOKGEN__LLM__PROVIDER = "gemini"
# Optional preflight: sends one small request using the configured model/key.
python -m bookgen.provider_check
python -m uvicorn bookgen.main:create_app --factory --host 127.0.0.1 --port 8000
```

On Windows, leave off `--reload`: Uvicorn's reload worker uses an event loop that cannot launch the Chromium subprocess Playwright needs for PDF export. Restart the API manually after changing Python files. On macOS/Linux, `--reload` is fine.

Next, open terminal 2 at the repository root. Activate the web app only if your project setup requires it (the Python `.venv` is not needed for Next.js), set the API origin, and start Next.js:

```bash
# macOS / Linux
NEXT_PUBLIC_API_ORIGIN=http://localhost:8000 npm --prefix apps/web run dev
```

```powershell
# Windows PowerShell
$env:NEXT_PUBLIC_API_ORIGIN = "http://localhost:8000"
npm --prefix apps/web run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser. Use `localhost` for the web app; the PDF renderer accesses its print page through `http://127.0.0.1:3000`, which is allowed for Next.js development in `apps/web/next.config.mjs`. The API docs are at [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).

To run without a Google key, set `BOOKGEN__LLM__PROVIDER=mock` in terminal 1 instead; generated content will use the mock provider. For Vertex AI, set `BOOKGEN__LLM__TRANSPORT_MODE=vertex` and configure Google Cloud Application Default Credentials with `gcloud auth application-default login`.

## Manual DEBUG mode

Enable the node-by-node debugger in the API terminal before starting or restarting
the API. It defaults to off and does not require a Gemini key:

```powershell
$env:BOOKGEN__APP__DEBUG_MODE = "true"
$env:PYTHONPATH = (Resolve-Path apps/api/src).Path
.\.venv\Scripts\python.exe -m uvicorn bookgen.main:create_app --factory --host 127.0.0.1 --port 8000
```

On macOS/Linux, set `BOOKGEN__APP__DEBUG_MODE=true` before the normal API command.
Start the web app as usual. Create or reopen a book in the regular Studio, then
use the **Open debugger** link in the book header. Generate the page from that
debugger workspace; normal Studio generation is not available while debug mode
is enabled.

1. The studio's **DEBUG · manual graph** panel pauses before `profile` and after
   every completed graph node. Inspect **Node input**, **Node output**, and
   **Current graph state**, then click **Run <node>** to advance.
2. At `generate_candidates`, click **Copy prompt** and paste into a separate chat.
   **Chat prompt** contains the actual system and strategy instruction text,
   global book context and semantic design grammar, bounded page/history data,
   and response JSON schema. These come from the same request used by the live
   provider. The chat version combines the system/user instructions and schema
   into one message; it does not include the SDK envelope or generation settings.
   If images are present, download the listed thumbnails and attach them to that
   chat in order. They are the same PNG thumbnails supplied to the provider,
   at most 768px; base64 image bytes are kept out of the copied prompt.
3. Paste the chat's returned `PageLayoutAST` JSON into **Manual LLM response**.
   The prompt asks for one JSON object without Markdown fences. Submit A, then B.
   The debug service makes no provider calls, including when `LLM.PROVIDER` is `mock`.
4. Advance `validate` to inspect schema/content errors. Repair requests use the
   same manual copy/paste flow and include the candidate and validation issues.
   Malformed JSON is retained for inspection and follows the configured repair
   cap and validated fallback. The debugger does not bypass validators.
5. Inspect **Theme tokens and semantic placeholders** for token values, CSS
   variables, renderer surface classes, and header/footer templates such as
   `{page_number}` and `{total_pages}`. Layouts still use semantic roles such as
   `brand_dark`; actual colors remain in the renderer's theme. At human review,
   compare the real rendered A/B previews and confirm a selection. Click
   **Run commit_page** separately to save the page.

Checkpoints and submitted responses persist in SQLite. Reload the page, use
**Reload checkpoint**, or restart the API with debug enabled to resume. Each
action is tied to the current pause; stale submissions return a conflict instead
of advancing another request. Submitted replies retain the exact request and
prompt shown at their pause, including after prompt configuration changes and
API restarts. Finish an existing pending page before switching
between normal generation and debugging. To return to normal mode, set
`BOOKGEN__APP__DEBUG_MODE=false` and restart the API.

The same flow is available through JSON endpoints under
`/api/v1/sessions/{session_id}` (also listed in `/docs`):

| Method | Path | Input / result |
| --- | --- | --- |
| `POST` | `/debug/pages` | Normal page input `{ "text": "Original copy", "asset_ids": [] }`; returns the first paused checkpoint |
| `GET` | `/debug` | Current state, last node input/output, pending `interrupts[].prompt` and separate `images` attachments or review, theme tokens, and opaque `checkpoint_id` |
| `POST` | `/debug/step` | `{ "checkpoint_id": "<latest>" }` at a node boundary; add `"response": "<raw JSON text>"` at an LLM pause or `"response": "option_a"` / `"option_b"` at review |

Always use the latest returned `checkpoint_id`, including between A and B.
Debug endpoints return `403` when the mode is disabled. While enabled, normal
`POST /pages` returns `409`; the debugger workspace submits new pages through
`POST /debug/pages`. The regular Studio does not switch to the debugger
automatically.
Inspection includes source text and manual responses, so use this mode in your
local development environment.

## Configuration

Configuration is loaded from `config/*.yaml` and validated with strict Pydantic settings. Environment variables use the `BOOKGEN__` prefix and `__` for nested fields; environment values override YAML. For example:

```bash
BOOKGEN__LLM__PROVIDER=mock
BOOKGEN__APP__SQLITE_URI=sqlite:///./bookgen.db
BOOKGEN__APP__STORAGE_ROOT=uploads
BOOKGEN__APP__CORS_ORIGINS='["http://localhost:3000"]'
BOOKGEN__EXPORT__PRINT_ORIGIN=http://127.0.0.1:3000
```

`NEXT_PUBLIC_API_ORIGIN` is read by the browser bundle. Set it to the API origin without a trailing slash. An empty value means same-origin API requests, which requires a reverse proxy that routes `/api` to FastAPI.

## Tests and quality gates

Run focused suites from the repository root:

```bash
# Python unit and graph tests
pytest -W error apps/api/tests/unit apps/api/tests/graph

# Python integration tests, including local Chromium/Next PDF export
pytest -W error apps/api/tests/integration

# Web unit tests and TypeScript typecheck
npm --prefix apps/web run test
npm --prefix apps/web run typecheck

# Browser end-to-end tests (Playwright starts the API and web servers)
make e2e
```

`make e2e` runs with one Playwright worker because the browser fixtures share a
SQLite session/checkpoint database. Parallel workers can contend for its write
lock; use this target for local and CI browser runs.

The Playwright configuration expects the API virtual environment at the repository root (`.venv`). If using another environment, set `PYTHON` to its Python executable before running E2E tests.

Validate or regenerate the API contract after schema or route changes:

```bash
make check-contracts
# After intentional API schema changes:
make sync-contracts
```

Run the complete repository gates and branch coverage:

```bash
make test
make coverage
```

`make test` installs browser dependencies, runs the Python suites, web unit tests, typecheck, and E2E. `make coverage` checks Python domain and graph branch coverage and web coverage. GNU Make and Bash are required for these targets. CI runs contract checks and the full test/coverage workflow; see [the workflow](.github/workflows/ci.yml).

## Deploy the web app to Vercel

Deploy the API first and keep its base URL. Vercel hosts the Next.js web app; it does not host this FastAPI service as part of the web project.

1. Import the Git repository as a Vercel project.
2. Set the **Root Directory** to `apps/web`. Keep Next.js auto-detection and the package scripts (`npm run build`, `npm run start`). Vercel supports selecting an app directory in a monorepo; see [Vercel monorepos](https://vercel.com/docs/monorepos).
3. Add `NEXT_PUBLIC_API_ORIGIN=https://<cloud-run-service-url>` to the Preview and Production environments. This value is included in the browser bundle, so configure it before each deployment and redeploy after changes. See [Vercel environment variables](https://vercel.com/docs/environment-variables) and [framework environment variables](https://vercel.com/docs/environment-variables/framework-environment-variables).
4. Add the exact Vercel production origin (for example, `https://books.example.com`) to the API’s `BOOKGEN__APP__CORS_ORIGINS` JSON list. Add preview origins only if the preview API is intended to accept them.
5. Deploy and verify the app can create a session, load assets, and export a PDF. PDF rendering requires the API to reach the deployed print page, configured with `BOOKGEN__EXPORT__PRINT_ORIGIN`.

For a CLI deployment, install the [Vercel CLI](https://vercel.com/docs/cli), link the project from `apps/web`, pull or configure its environment variables, then run `vercel --prod` from that directory.

## Deploy the API to Google Cloud Run

### Important storage and access constraints

The API currently uses SQLite and local asset files. Cloud Run’s writable filesystem is in-memory and instance-local; it is lost when an instance stops and consumes instance memory. The steps below use `/tmp` and are suitable only for a demo with disposable data. Do not treat this as durable production storage. See Google’s [Cloud Run container contract](https://cloud.google.com/run/docs/container-contract).

The current API also has no user authentication or per-user authorization. `--allow-unauthenticated` makes it reachable by anyone who can reach the service URL. Use non-sensitive demo data only until an authentication and authorization layer and durable storage adapters are implemented and reviewed.

### 1. Create a Cloud Run container

Cloud Run needs the API package **and** the repository-root `config/` directory. Build from the repository root. Save the following as `Dockerfile` in the repository root (do not use `apps/api` as the build context):

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/apps/api/src

WORKDIR /app
COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/src /app/apps/api/src
COPY config /app/config

RUN pip install --no-cache-dir /app/apps/api \
    && python -m playwright install --with-deps chromium \
    && useradd --system --uid 10001 --create-home app \
    && mkdir -p /tmp/bookgen \
    && chown -R 10001:10001 /tmp/bookgen

USER 10001:10001
ENV BOOKGEN__APP__SQLITE_URI=sqlite:////tmp/bookgen/bookgen.db \
    BOOKGEN__APP__STORAGE_ROOT=/tmp/bookgen/uploads

CMD ["sh", "-c", "exec uvicorn bookgen.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
```

The image includes Chromium because PDF export launches a local browser. Build and push it to Artifact Registry:

```bash
export PROJECT_ID="your-gcp-project"
export REGION="us-central1"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/bookgen/visual-book-generator-api:$(git rev-parse --short HEAD)"

gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com
gcloud artifacts repositories create bookgen --repository-format=docker --location="$REGION"
gcloud builds submit --tag "$IMAGE" .
```

Create the Artifact Registry repository once. If it already exists, skip that command.

### 2. Configure the runtime identity and environment

For Vertex AI, create a dedicated runtime service account and grant it only the Vertex AI role needed by the application:

```bash
gcloud iam service-accounts create bookgen-runtime --display-name="Visual Book Generator runtime"
export RUNTIME_SA="bookgen-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/aiplatform.user"
```

Create a local, untracked `cloudrun.env.yaml` with the deployed Vercel origin and the Cloud Run service URL not yet required:

```yaml
BOOKGEN__LLM__PROVIDER: gemini
BOOKGEN__LLM__TRANSPORT_MODE: vertex
BOOKGEN__APP__CORS_ORIGINS: '["https://books.example.com"]'
BOOKGEN__EXPORT__PRINT_ORIGIN: https://books.example.com
```

Do not put API keys or service-account keys in this file. The example uses Cloud Run’s attached service account and Application Default Credentials. For Gemini Developer API credentials, store the key in Secret Manager and attach it as a Cloud Run secret instead of putting it in source or a plain environment file.

### 3. Deploy and smoke-test

```bash
gcloud run deploy visual-book-generator-api \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="$RUNTIME_SA" \
  --port=8080 \
  --cpu=2 \
  --memory=2Gi \
  --concurrency=1 \
  --max=3 \
  --timeout=300 \
  --env-vars-file=cloudrun.env.yaml
```

The service must be reachable from the browser because the web app calls it directly. The CORS origin must match the deployed web origin exactly. After deploy, retrieve the service URL and check the API contract:

```bash
export API_URL="$(gcloud run services describe visual-book-generator-api --region="$REGION" --format='value(status.url)')"
curl --fail "$API_URL/openapi.json"
```

Set that `API_URL` as Vercel’s `NEXT_PUBLIC_API_ORIGIN`, then redeploy the Vercel project. Keep `BOOKGEN__EXPORT__PRINT_ORIGIN` pointed at the matching Vercel deployment so the API’s Chromium renderer loads the correct print UI. For previews, use matching preview web/API configuration rather than sharing production origins.

Cloud Run’s source deployment is also available through `gcloud run deploy --source`; this repository uses a root Docker build because the runtime requires both `apps/api` and the root `config/` tree. See [Cloud Run source deployment](https://cloud.google.com/run/docs/deploying-source-code) and [container deployment](https://cloud.google.com/run/docs/deploying).

## Production readiness

Before using this service for customer books or sensitive content, close these deployment gaps:

- Replace SQLite and local assets with durable, concurrency-safe managed storage. Cloud Run scaling and restarts cannot preserve instance-local files.
- Add authentication, authorization, tenant isolation, and abuse/rate controls. The current API routes are not protected by an identity layer.
- Set up database migrations, backup/restore, retention, and recovery procedures when durable storage is introduced.
- Store provider credentials in a secret manager; prefer workload identity/ADC over downloaded service-account keys.
- Configure least-privilege runtime and build service accounts, deployment approvals, and separate preview/staging/production environments.
- Set monitoring and alerting for API errors, export duration/failures, browser memory, and provider usage. Test rollback and restore procedures.
- Review privacy, compliance, and data-retention requirements for source text, images, metrics, generated files, and model-provider calls.

## Development guidelines

Open **Examples** in Studio to review any of the 25 local marketing scenarios.
Every opening creates an independent book with its own assets and a durable
scripted provider binding. No model key or external asset download is required;
review, editing, compliance decisions and PDF export use the ordinary workflow.
The page identifies the run as a scripted fixture.

`make golden` runs the offline manifest, isolation, compliance and 20-page rhythm
gates. The golden tests also run in `make backend`, `make test` and `make coverage`.
The full browser suite (`make e2e`) exports all 25 examples, checks overflow and
preview/PDF parity against configured drift bounds, and compares the three art
direction anchors with the reviewed Ticket 20 screenshots. CI preserves the
case/direction-labeled previews, print screenshots, PDFs and measurement reports
in the `scripted-fixture-runs` artifact. Ordinary first-pass validity is gated at
90%; deliberate repair and fallback fixtures are reported separately. These are
scripted fixture runs, not live-model quality measurements. See the
[corpus guide](apps/api/src/bookgen/examples/README.md) for report paths and details.
CI enables `BOOKGEN__APP__DEBUG_MODE=true` for `make test` so the optional manual
debugger browser flows also execute; use the same variable to include them locally.

- Keep provider-generated layouts within the constrained `PageLayoutAST` grammar. The model must not author HTML, CSS, colors, or arbitrary pixel spacing.
- Preserve user text through source block pointers; do not ask the model to rewrite body copy.
- Keep `CHART` and `DIAGRAM` assets uncropped with `object-contain`.
- Load model, retry, word-budget, prompt, and design parameters from typed YAML configuration.
- Edit canonical Pydantic schemas first and regenerate TypeScript contracts with `make sync-contracts`.
- Use `MockLLMProvider` in tests; never make live model calls in unit or graph tests.
- Follow [AGENTS.md](AGENTS.md) and the ticket workflow in [`tasks/BACKLOG_DAG.md`](tasks/BACKLOG_DAG.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Browser reports a CORS error | `BOOKGEN__APP__CORS_ORIGINS` must contain the exact web origin, including scheme and hostname. |
| Web app cannot reach the API | Set `NEXT_PUBLIC_API_ORIGIN` before building/deploying and redeploy after changing it. |
| PDF export cannot load the print page | Set `BOOKGEN__EXPORT__PRINT_ORIGIN` to a reachable web deployment; ensure Chromium is installed in the API image. |
| API fails to load YAML or prompts in a container | Preserve the repository-root `config/` tree at `/app/config` and set `PYTHONPATH=/app/apps/api/src`. |
| E2E cannot start the API | Confirm root `.venv` exists or set `PYTHON` to the Python executable that has the API test dependencies installed. |
| Contract check needs Bash | Install Git Bash on Windows or run the commands in a shell with GNU Bash. |

## License and third-party assets

The bundled Inter and Source Serif 4 web fonts include their SIL Open Font License notices under `apps/web/public/fonts/`. Review dependency licenses and third-party notices before redistributing a production container or book output.
