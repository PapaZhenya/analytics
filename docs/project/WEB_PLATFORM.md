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
- **Tests** (`backend/tests/`, pytest): **16 tests total.**
  - **10 run and pass right now** without any external services: password/JWT
    round-trips (`test_security.py`), and the QA engine's keyword evaluator + schema
    rejection of malformed verdicts/out-of-range confidence (`test_qa_engine.py`).
  - **6 require a real PostgreSQL instance** (native UUID/JSONB/ENUM types used
    throughout the schema aren't reproducible on SQLite): login/RBAC
    (`test_auth_and_permissions.py`), upload checksum-dedup
    (`test_upload_dedup.py`), and orchestrator crash-resumability
    (`test_idempotency.py`). These are correctly collected and **skip cleanly** (not
    fail) without `TEST_DATABASE_URL` set — this sandbox has no Postgres/Docker
    available to run them against. Set `TEST_DATABASE_URL` to a disposable Postgres DB
    (e.g. the docker-compose `postgres` service) to run the full 16.
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
