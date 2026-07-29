# Call-Center QA Analytics Platform — Phase 1 (MVP) Implementation Notes

This documents what was actually built against the approved plan
(`Call-Center QA Analytics Platform — Architecture & Phase 1 Implementation Plan`), what
was verified and how, and what still needs a real environment (Postgres/Redis/GPU) to
exercise end-to-end. It complements, not replaces, the earlier read-only audit
(`PROJECT_ARCHITECTURE.md`, `PIPELINE.md`, `MODULES.md`, `REUSE.md`) — this repo now has
both a documented legacy pipeline **and** a new product layer built on top of it.

## What exists now

```
analytics/
  backend/         FastAPI app, SQLAlchemy models, Alembic migrations, Celery tasks,
                    pipeline orchestrator + QA rule engine, pytest suite
  frontend/        React + TypeScript SPA (Vite), component tests, production build
  src/             UNCHANGED pipeline library (two dead classes removed — see below)
  config/          UNCHANGED (config.yaml, prompt.yaml, nemo/)
  docker-compose.yml, .env.example
```

## Architecture decisions — justification

Section 4 of the product spec requires every major technology choice to be explained
and grounded in the repository audit rather than assumed, and explicitly favors a
**modular monolith plus background workers** over heavier infrastructure (Kafka,
Kubernetes, RabbitMQ, Elasticsearch, microservices) unless the repo demonstrates a real
need for it. This project doesn't — it's a single-tenant, single-team QA platform with
one audio-processing pipeline, so the decisions below default to the simplest option
that satisfies the requirements, not the most scalable one in the abstract.

| Decision | Why | Rejected alternative(s) |
|---|---|---|
| **FastAPI** | The existing pipeline is already async Python (`main.py`'s `async def main`); FastAPI's async request handling, Pydantic-native validation, and auto-generated OpenAPI schema fit directly on top without an adapter layer. | Django (batteries-included but the project has no need for Django's ORM/admin/templating — would mean fighting the framework to get async pipeline integration and a thin API); Flask (would need bolting on async support and OpenAPI generation by hand). |
| **PostgreSQL** | Multi-role concurrent access (QA reviewers, managers, admins working simultaneously) needs real concurrent-write support the legacy SQLite schema (`src/db/sql/Schema.sql`) doesn't provide; native `UUID`/`JSONB`/`ENUM` types map directly onto the schema's needs (scorecard criteria config, versioning, RBAC). | SQLite (fine for the original single-process pipeline, not for a multi-user web app — see `docs/project/REUSE.md` §"заменить"); MySQL (no strong reason to prefer over Postgres here, and Postgres's native enum/JSONB support is a better fit for this schema). |
| **Alembic** | The de facto standard migration tool for SQLAlchemy; the initial migration is mechanically generated from the ORM models (`sqlalchemy.create_mock_engine`) rather than hand-written, so schema and migration can't drift apart. | Hand-rolled SQL migrations (error-prone, no dependency-graph/downgrade support); Django migrations (not applicable — not using Django). |
| **Redis + Celery** | Redis: already the natural choice once Celery is chosen (broker+result backend in one process, minimal ops surface, no separate message broker to run). Celery: the most mature Python background-job system with exactly the features needed — retries (`max_retries`, `acks_late`), dedicated queues (GPU-only `pipeline_gpu` queue with `--concurrency=1` per GPU to avoid CUDA OOM), and task tracking, all things a from-scratch or lighter framework would need to be built by hand. | RQ (simpler, but weaker retry/queue-routing story — would need hand-rolled GPU-queue isolation); Dramatiq/Arq (viable, but no concrete advantage here over Celery's maturity and this project's straightforward one-task-per-call model — see `backend/pipeline/orchestrator.py`'s docstring for why it's one task per call, not per pipeline stage). |
| **React + TypeScript (Vite)** | A single-page app is the natural fit for a highly interactive review screen (audio player synced to transcript synced to QA findings) — there's no SEO/server-rendering requirement that would justify Next.js's added complexity (routing conventions, server components, deployment model) for an internal business tool behind auth. | Next.js (no requirement here actually needs SSR/SSG — would add build/deploy complexity without a corresponding benefit); Vue/Svelte (no reason to deviate from the most common choice for a team that may not be React-specialized but is broadly familiar with it). |
| **Docker Compose (not Kubernetes)** | Five services (api, worker, postgres, redis, frontend) on what's expected to be a single box or small on-prem deployment (per the product spec's "local-first" framing) — Kubernetes' value (multi-node scheduling, rolling deployments across a fleet) doesn't apply at this scale and would add an entire operations discipline the project doesn't need yet. | Kubernetes (justified only if/when this needs to run across multiple nodes or auto-scale — not a stated requirement); bare-metal/systemd (loses the reproducible-build/isolation benefits Docker gives for free). |
| **Local filesystem storage (dev) + S3-compatible (production option)** | `AudioStorage` is an interface with two implementations (`LocalFilesystemStorage`, `S3CompatibleStorage`) selected by `STORAGE_BACKEND` — local for simple/on-prem deployments (matches the original repo's own `.data/` convention), S3-compatible (real AWS S3 or MinIO) when durability/multi-host access is needed. Neither is hardcoded — callers only ever see the interface. | A single storage backend only (would force either "S3 always" — overkill for a local-first single-box deployment — or "local always" — no durable-storage story for production). |
| **Structured (JSON) logging, stdlib-only** | A custom `logging.Formatter` (`backend/app/logging_config.py`) is enough to get parseable, one-object-per-line logs with request/task metadata (`call_id`, `duration_ms`, etc.) attached — exactly what's needed, nothing more. | `structlog`/`python-json-logger` (real libraries, but this project's logging needs — timestamp, level, message, a few extra fields, exception formatting — don't need a dependency to get; adding one here would be exactly the "infrastructure without a demonstrated need" section 4 warns against). |
| **Typed API contracts** | Pydantic models (backend) are the single source of truth for request/response shapes, auto-published as an OpenAPI schema (`/openapi.json`, `/docs`); the frontend's TypeScript interfaces (`frontend/src/api/*.ts`) mirror them by hand today. | Fully generated shared types (e.g. `openapi-typescript` codegen) would remove the hand-mirroring step entirely — flagged as a reasonable Phase 2+ tightening, not done now since it's a tooling addition, not a missing capability. |

## Backend — verified

- **31 SQLAlchemy models / tables**, matching the plan's schema exactly (org structure,
  extensible speaker_roles, calls + processing steps + acoustic metrics, versioned
  scorecards/criteria, QA evaluations/findings/evidence, review_actions audit log,
  comments, ingestion_sources placeholder), plus `refresh_tokens` (added during
  implementation — needed for real token rotation/revocation, see Auth below).
- **Alembic migrations** (`0001_initial_schema`, `0002_seed_reference_data`,
  `0003_refresh_tokens`) — the DDL in `0001` is mechanically generated from the ORM
  models via `sqlalchemy.create_mock_engine` (not hand-typed), so it can't drift from
  them. Verified: `alembic history` resolves the chain cleanly; a bug where SQLAlchemy's
  `Enum` was about to persist Python member *names* instead of *values* (e.g.
  `Verdict.pass_` → `'pass_'` in the DB instead of `'pass'`) was caught and fixed via a
  `pg_enum()` helper (`backend/app/db/base.py`) before it ever reached a migration.
- **Full API surface** from the plan (auth, calls, findings, comments, scorecards,
  projects, teams, health) — verified by importing the FastAPI app and confirming every
  planned route registers with no import errors.
- **Auth**: argon2 password hashing, JWT access tokens + httpOnly-cookie refresh tokens
  with server-side rotation/revocation (`refresh_tokens` table — each use revokes the old
  jti and issues a new one), RBAC enforced via `require_permission()` reading a
  `role_permissions` matrix (never frontend-only).
- **QA rule engine** (`backend/pipeline/qa_engine/`): schema-validated `CriterionResult`
  (Pydantic) that every evaluator must produce before a result is ever persisted;
  `KeywordEvaluator` and `SemanticEvaluator` implemented for Phase 1; every other
  `rule_type` is a pure future addition (new evaluator module + enum value), not an
  architecture change.
- **Pipeline orchestrator** (`backend/pipeline/orchestrator.py` + `steps.py`): wraps the
  existing `src/audio/*`/`src/text/*` classes unchanged, adds idempotent
  crash/restart resumability (JSON checkpoint per call + per-step DB status, so a killed
  worker resumes from the last succeeded step instead of reprocessing from scratch), and
  never deletes the original recording (only `.temp/` working files).
- **Tests** (`backend/tests/`, pytest): **28 tests total.**
  - **19 run and pass right now** without any external services: password/JWT
    round-trips (`test_security.py`), the QA engine's keyword evaluator + schema
    rejection of malformed verdicts/out-of-range confidence (`test_qa_engine.py`), the
    structured-logging JSON formatter (`test_logging_config.py`), and validation of raw
    LLM output — malformed sentiment/profanity/summary/conflict/topic items are dropped
    with a logged reason rather than crashing or being trusted as-is
    (`test_llm_schemas.py`).
  - **9 require a real PostgreSQL instance** (native UUID/JSONB/ENUM types used
    throughout the schema aren't reproducible on SQLite): login/RBAC
    (`test_auth_and_permissions.py`), upload checksum-dedup
    (`test_upload_dedup.py`), orchestrator crash-resumability
    (`test_idempotency.py`), QA-evaluation retry idempotency
    (`test_qa_evaluation_idempotency.py`), and the two explainability-history endpoints
    end to end through the actual API (`test_explainability_history.py`). These are
    correctly collected and **skip cleanly** (not fail) without `TEST_DATABASE_URL`
    set — this sandbox has no Postgres/Docker available to run them against. Set
    `TEST_DATABASE_URL` to a disposable Postgres DB (e.g. the docker-compose
    `postgres` service) to run the full 28.
  - **Not run in this sandbox at all**: an actual pipeline run against a real audio file
    needs the full ML stack (torch, nemo_toolkit, faster-whisper, demucs, pyannote.audio,
    ctc-forced-aligner, MPSENet — multi-GB, GPU-oriented). The orchestrator/steps code was
    verified by static import (no heavy deps loaded until a step function actually runs)
    and by the mocked-step idempotency test above, but a true end-to-end pipeline run
    (Verification item 2 in the approved plan) still needs to happen in a real
    GPU-equipped environment before Phase 1 is considered fully done.

## Local-first / no silently-required external AI API

The user's spec (section 3 of the product requirements) requires that the default
production mode never depend on an external AI API, with audio/transcripts/QA
results/feedback capable of staying entirely inside customer infrastructure, and any
external provider as an explicit opt-in adapter — never a silent default.

**This was a real, already-shipped violation, not just a future design goal**: the
initial Phase 1 implementation hardcoded `model_id="openai"` in all 6 LLM-driven
pipeline steps (`backend/pipeline/steps.py`) and in the QA engine's
`SemanticEvaluator` (`backend/pipeline/qa_engine/semantic_evaluator.py`) — meaning
every processed call silently sent transcript data to OpenAI regardless of any
configuration. Fixed by:

- Adding `Settings.llm_provider` (`backend/app/config.py`, env var `LLM_PROVIDER`),
  **defaulting to `"llama"`** — the existing, already-implemented
  `src/text/model.py::LLaMAModel`, which runs a HuggingFace `transformers`/`torch` model
  locally on the worker (`config/config.yaml`'s `models.llama.model_name`, currently
  `meta-llama/Llama-3.2-3B-Instruct`). No data leaves the deployment at runtime with this
  default.
- Every call site that previously hardcoded `model_id="openai"` now reads
  `settings.llm_provider` instead — `"openai"`/`"azure_openai"` only ever get used if an
  operator explicitly sets `LLM_PROVIDER` in `.env`.
- This required **zero changes** to `src/text/model.py`'s `ModelRegistry`/`ModelFactory`
  pattern — that pluggable-provider design already existed in the original repo; Phase 1
  just wasn't using it correctly. Same for the audio pipeline: pyannote, MPSENet, Demucs,
  faster-whisper, NeMo, ctc-forced-aligner, and deepmultilingualpunctuation were already
  fully local (one-time model-weight downloads, then local inference) and needed no
  changes at all — they never had a runtime external-API dependency to remove.
- Remaining caveat, documented rather than silently glossed over: the **default** local
  model (`meta-llama/Llama-3.2-3B-Instruct`) is gated on HuggingFace and needs a
  `HUGGINGFACE_TOKEN` to *download* once — a one-time credential for fetching weights,
  not a runtime API call. A deployment wanting zero external credentials of any kind
  should swap `models.llama.model_name` in `config/config.yaml` to an ungated model
  (e.g. a Qwen2.5 or Phi-3.5 instruct checkpoint) — not done here since changing the
  actual model choice is a quality/behavior decision, not a plumbing fix.
- Core-vs-optional separation is now explicit in `.env.example`: `LLM_PROVIDER` plus
  `HUGGINGFACE_TOKEN` are the only credentials needed for the local-only default;
  `OPENAI_API_KEY`/`AZURE_OPENAI_*` are clearly marked as read only when an operator
  opts into an external provider.

Section 3's other listed components (STT, diarization, speaker-role assignment,
embeddings, storage) were already local by construction and needed no change; "local
semantic analysis"/"local language models" beyond the fix above is exactly what the
`ModelRegistry`/`ModelFactory` extensibility point already supports (register a new
local model class, select it via `LLM_PROVIDER`) — no architecture change required to
add one. Local analytics (Phase 2, not yet built) is already planned in the approved
architecture plan to be SQL views against the local Postgres instance, not an external
analytics service.

## Frontend — verified

- Vite + React + TypeScript SPA implementing every Phase 1 page/component from the plan:
  `LoginPage`, `CallListPage` (filter/paginate/status polling), `UploadPage`
  (drag-and-drop, multi-file, per-file progress), `CallReviewPage` composing
  `AudioPlayer` (wavesurfer.js — play/pause/seek/speed), `TranscriptPanel`
  (speaker-colored, click-to-seek, search-highlight, correction-aware), `QAScorePanel`,
  `FindingCard`/`EvidenceChip` (evidence click → audio seek), `CommentThread`.
- **`npx tsc -b --noEmit`** — passes with zero errors.
- **`npx vitest run`** — 5/5 component tests pass, including the exact behavior called
  out in the plan's Verification section: clicking a transcript segment/evidence chip
  seeks the audio player to the right timestamp, and the currently-playing segment
  highlights correctly.
- **`npm run build`** — production bundle builds successfully.

## What was NOT run in this session (needs a real environment)

1. **`docker-compose up`** — Docker isn't available in this sandbox. `docker-compose.yml`,
   `backend/Dockerfile.api`, `backend/Dockerfile.worker`, and `frontend/Dockerfile` are
   written and internally consistent (verified by reasoning through every path/env var
   they reference, matching them against `backend/app/config.py`), but the actual
   `docker-compose up` smoke test from the plan's Verification section #6 has not been
   executed. Do this first before relying on the stack.
2. **Bootstrap steps** — after `docker-compose up` and `alembic upgrade head` run:
   - `python -m backend.scripts.create_superuser --email you@company.com --password '...'`
     (deliberately not a seeded migration row — a fixed default admin/password baked into
     a migration is a real vulnerability, so this is an explicit manual step).
   - `python -m backend.scripts.seed_example_scorecard` (needs the superuser to exist
     first — a scorecard's `created_by` is a real FK to `users`).
3. **A real pipeline run** against one of `.data/example/*.mp3` through the actual worker
   container (GPU-equipped), confirming the full call → transcript → QA finding → review
   loop end to end.

## Data integrity & auditability (section 8 of the product spec)

Section 8 lists what must be preserved (file identity, source metadata, processing
history, model versions, scorecard version, automatic vs. human-corrected results,
reviewer identity/timestamps, transcript revisions, audit events) and — separately —
what a manager must be able to *determine* from a historical report (why a call got a
score, which rule produced it, which evidence, which model/engine version, whether and
who changed it, when). Auditing against this found the data was already **stored** for
nearly everything, but not all of it was actually **reachable through the API** — which
is what "explainable" requires; a fact sitting in a column nobody's endpoint returns
isn't explainable to a manager using the product.

Fixed:

- `CallDetailResponse` now includes `checksum`, `uploaded_by`, `channel_count`,
  `is_separate_channel_recording`, and `model_versions` — all were already columns on
  `Call` (added during the section 5 audio-pipeline work) but never reached this
  response until now.
- `FindingOut` now includes `rule_type` and `engine_version` (which rule/engine version
  produced this specific result — previously only inferable by cross-referencing
  `Call.model_versions` and guessing) and `reviewed_at`.
- `QAEvaluationOut` now includes `scorecard_version`/`scorecard_name` (via a new
  `QAEvaluation.scorecard` relationship) — a historical report must show which
  scorecard *version* it was scored against, not the current state of a scorecard that
  may have since been re-versioned.
- `SpeakerOut` now includes `role_corrected_by`/`role_corrected_at` — previously only a
  boolean `role_manually_corrected` was exposed, answering *that* it was corrected but
  not *who* or *when*.
- **New:** `GET /findings/{id}/history` — every `ReviewAction` ever taken on a finding,
  in order (action type, previous → new verdict, reviewer, timestamp, notes). Full
  history, not just the finding's current state.
- **New:** `GET /calls/{id}/utterances/{id}/history` — every `UtteranceCorrection` ever
  applied to an utterance, in order. The original ASR text is never in this list — it's
  immutable on the `Utterance` row itself and always visible via `GET /calls/{id}` — this
  is purely the revision chain layered on top of it.
- Frontend: a collapsible "Call details & processing metadata" panel
  (`CallInfoPanel.tsx`) surfaces checksum/channels/model-versions; `FindingCard` shows
  rule type + engine version inline and a "Who changed this, and when?" toggle that
  fetches and renders the full review history; `QAScorePanel` shows the scorecard name
  and version.

Everything else on the section 8 checklist was already correctly modeled and confirmed
by direct inspection: `Scorecard.group_id`/`version` with a hard immutability
convention once published (and, in Phase 1, there is literally no API endpoint that
could mutate a published scorecard's criteria — the admin scorecard-editor UI is
Phase 2, so the convention can't yet be violated via the API even without an explicit
runtime guard); `UtteranceCorrection` and `ReviewAction` as append-only logs;
`AuditLog` for account/role-level events (login, speaker-role correction).

## Engineering quality audit (section 6 of the product spec)

Section 6 is a checklist of engineering-discipline rules for a long-lived commercial
system. Auditing the already-built Phase 1 code against it found four real violations
— fixed, not just checked off:

- **Insecure default secret.** `Settings.jwt_secret_key` had a hardcoded fallback
  (`"change-me-in-.env"`). An operator who forgot to set `JWT_SECRET_KEY` would get a
  fully working app silently signing real JWTs with a secret published in this repo's
  own source. Fixed: the field now has no default — `pydantic-settings` raises a clear
  startup error if it's missing, fail-closed instead of fail-open. (Tests set a
  test-only value via `backend/tests/conftest.py`; this is never a real deployment's
  secret.)
- **Unvalidated AI output reaching persistence.** The QA engine's `CriterionResult`
  schema (see `MODULES.md`) already enforced "never trust raw AI output," but the
  older sentiment/profanity/summary/conflict/topic steps (reusing `LLMOrchestrator`
  unmodified) only had ad hoc `.get()` defensive coding — a single malformed item
  (e.g. a sentiment entry missing `"index"`) would raise an unhandled `KeyError` and
  crash the whole `persist_results` step. Fixed: `backend/pipeline/llm_schemas.py`
  validates every LLM-returned item independently (Pydantic); a bad item is logged and
  dropped, not a crash, and not silently trusted.
- **Non-idempotent QA re-evaluation.** `qa_engine/orchestrator.py::run_scorecard` had
  no retry protection: if the `qa_evaluation` pipeline step failed partway through and
  Celery retried it, the partial `QAEvaluation`/`QAFinding` rows from the failed attempt
  were orphaned in the DB while a second, complete set was inserted alongside them.
  Fixed: `_clear_unreviewed_evaluation` removes a prior unreviewed evaluation for the
  same call+scorecard before creating a new one — but **only** if it has zero
  `review_actions` logged against it, so a result a human has actually looked at can
  never be silently replaced (the actual substance of "do not silently alter historical
  QA results").
- **One large router file mixing concerns.** `routers/calls.py` had grown to ~400 lines
  spanning call-lifecycle CRUD, audio streaming, and transcript/speaker-role correction
  — three genuinely different responsibilities. Split into `routers/calls.py` (call
  lifecycle), `routers/audio.py` (streaming), `routers/transcripts.py` (corrections);
  the shared `get_call_or_404` helper moved to `dependencies.py` instead of being
  copy-pasted across the three (also resolves a "do not create duplicate
  abstractions" instance).

Also surfaced and fixed in the frontend: `UploadPage`'s error handler discarded the
backend's actual error detail (e.g. "duplicate of existing call") in favor of a generic
"Upload failed" string — silently hiding exactly the information a user needs to fix
the problem. Now surfaces the real `detail` from the API response.

Everything else on the section 6 checklist was already satisfied by the existing
design and confirmed by direct inspection rather than assumed: no giant classes,
scorecards are DB-driven data (not hardcoded Python), migrations exist for every schema
change (0001-0004), config is env-driven throughout, and the record-then-re-raise
pattern used for every broad `except Exception` in the pipeline (`orchestrator.py`,
`steps.py`, `process_call.py`) logs/records the failure rather than swallowing it.

## Audit fixes applied during this build

- Removed `Denoiser` (`src/audio/preprocessing.py`) — was dead code, unused anywhere in
  the pipeline, superseded by `SpeechEnhancement`.
- Deleted `src/text/prompt.py` (`PromptManager`) entirely — was dead code, duplicated
  `LLMOrchestrator`'s own prompt loading, and referenced a config file
  (`config/prompts.yaml`) that didn't even exist.
- Added an inline warning on `AzureOpenAIModel` (`src/text/model.py`) documenting that it
  uses the pre-1.0 `openai` SDK API and will raise under the pinned `openai==1.57.0` — it
  is not selected anywhere in the new backend.
- Original audio is never deleted by the new upload/processing path (permanent storage
  via `AudioStorage`, `Cleaner` only ever scoped to `.temp/`).
- The hardcoded binary `Customer`/`CSR` role model is replaced **at the database/schema
  level** (`speaker_roles` table: agent/client/other/unknown, extensible without a
  migration). Note a deliberate scope decision: `LLMResultHandler`
  (`src/text/llm.py`, unmodified) still internally validates/labels roles as literal
  `"Customer"`/`"CSR"` strings — rather than edit that class or its prompt contract
  (which the plan says to avoid rewriting), `backend/pipeline/steps.py` treats those two
  labels as opaque and translates them onto `speaker_roles` codes only at the persistence
  boundary in `orchestrator.py`. The generalization lives in the schema and the new code
  around it, not by touching the existing class.
- Acoustic metrics' audio source is now explicit and auditable
  (`acoustic_metrics.source_audio_variant`), set to `'original'` to match the existing
  pipeline's behavior rather than left implicit.

## Phase 2+ reminder

Everything beyond the MVP core loop — manager analytics/dashboard, full admin console,
telephony connectors, exports, model management — is intentionally **not** implemented
yet. See the "Full-Vision Architecture" and "Phase 2+ roadmap" sections of the approved
plan for what those look like architecturally; the schema and code here were built to not
foreclose any of it (e.g. `ingestion_sources`, the `RuleEvaluator` plugin pattern, the
`scorecards.group_id`/`version` immutability design).
