# Development Stages — Retrospective Mapping & Forward Plan

Section 10 of the product spec requires the product be built in gated stages (0–11),
each with defined scope, acceptance criteria, tests, migration notes, documentation
changes, and a completion report — explicitly warning against implementing the whole
product in one uncontrolled pass.

**This section arrived after most of the work below was already done**, driven by
sections 1–9 of the spec arriving one at a time and each being audited/fixed against
the existing implementation. This document does two things honestly: (1) maps what
actually happened onto this staging model — including where the *real* process
deviated from clean stage-by-stage gating, not a retouched version of history — and
(2) defines the forward plan for the stages that are genuinely not started yet, so
*those* proceed under the discipline this section asks for.

## How the actual process compared to this model

The real sequence was: a read-only repository audit (matches Stage 0 closely), then an
architecture-and-implementation plan reviewed and approved by the user via plan mode
(matches Stage 1 closely), then **one large implementation pass** covering what this
model separates into Stages 2 through 8, delivered as a single reviewed, tested,
committed unit (`3efd083`) — followed by a series of targeted correction passes as
sections 3–9 of the spec arrived, each auditing the already-built system and fixing
real gaps found (commits `e30f236` through `f16d5a3`).

That first big pass is the one honest deviation from this section's letter: Stages
2–8 were not gated individually with separate acceptance sign-off between them — they
were scoped together as "Phase 1 MVP" and approved as one unit before any code was
written (`ExitPlanMode` approval on the plan in `polished-drifting-papert.md`), which
is a form of consolidated sign-off, but not the same thing as eight separate
stage-gate approvals. Stated plainly rather than retroactively reframed as compliant.

What the process *did* get right, and would again: nothing beyond the approved Phase 1
scope was attempted preemptively — Stages 9 and 10 were explicitly deferred at
plan-approval time and still haven't been touched; every subsequent correction pass
came with tests, migration notes (where schema changed), and a documentation update
before being reported done.

## Stage-by-stage status

### Stage 0 — Repository audit
**Status: ✅ Complete.** Scope: understand the existing Callytics pipeline file-by-file
before touching anything. Acceptance: a full file/class/data-flow map, a pipeline
diagram, and an honest reuse/replace/delete assessment. Delivered as
`PROJECT_ARCHITECTURE.md`, `PIPELINE.md`, `MODULES.md`, `REUSE.md` — read-only, no code
changed, no dependencies installed, matching the explicit constraints given for this
stage. No tests/migrations applicable (analysis only).

### Stage 1 — Target product and architecture specification
**Status: ✅ Complete.** Scope: turn the product requirements into a concrete
architecture (stack choices with justification, data model, API surface, phased
roadmap) and get explicit sign-off before writing code. Delivered via `EnterPlanMode` →
a written plan (`polished-drifting-papert.md`) → clarifying questions asked and
answered (stack, tenancy, ingestion, auth) → `ExitPlanMode` approval. Completion
report: the approved plan itself, still on disk, referenced by `WEB_PLATFORM.md`.

### Stage 2 — Foundation and project structure
**Status: ✅ Complete** (bundled into the Stage 2–8 pass, `3efd083`). Scope: repo
layout (`backend/`, `frontend/`), config loading (`pydantic-settings`), Docker
Compose topology, dependency manifests. Acceptance: the app imports and boots, Docker
services are defined, no secrets committed. Tests: import/boot smoke-checks (see
`WEB_PLATFORM.md`'s verification notes). Docs: `WEB_PLATFORM.md`.

### Stage 3 — Database, authentication, and organization model
**Status: ✅ Complete.** Scope: schema (users/roles/permissions/organizations/
projects/teams/agents), Alembic migrations, JWT+argon2 auth, RBAC. Acceptance: 6 roles
seeded, permission matrix enforced server-side, migrations apply cleanly
(`alembic history` resolves `0001`→`0004`). Migration notes: `0001_initial_schema.py`
(mechanically generated from the ORM models, not hand-typed — see that file's
docstring), `0002_seed_reference_data.py`. Tests: `test_security.py`,
`test_auth_and_permissions.py`. Docs: `WEB_PLATFORM.md`'s architecture-decisions
table; `SECURITY.md` for the auth-specific hardening added later (section 9).

### Stage 4 — Upload and processing queue
**Status: ✅ Complete**, hardened later. Scope: `AudioStorage` abstraction
(local + S3), upload endpoint, Celery/Redis task queue with per-call idempotent
resumability. Acceptance: duplicate/oversized/wrong-type uploads rejected with clear
errors; a queued call resumes from its last completed step after a simulated crash.
Migration notes: `0004` added `channel_count`/`model_versions` columns used by this
stage's later hardening. Tests: `test_upload_dedup.py`, `test_idempotency.py`. Docs:
`WEB_PLATFORM.md`, `SECURITY.md` (file-size limits, upload rate limiting, audit
logging — added in the section 9 pass, `f16d5a3`).

### Stage 5 — Speech pipeline integration
**Status: ✅ Complete**, substantially extended after the initial pass. Scope: wrap
the existing `src/audio/*`/`src/text/*` classes (unmodified) behind
`backend/pipeline/orchestrator.py`/`steps.py`. Initial acceptance (`3efd083`): the 18
original steps run through the new orchestrator with checkpointed resumability.
Extended acceptance (`87b2003`, driven by section 5 of the spec): file validation and
channel inspection added as real new stages; model-version tracking added; long-call
time limits added; overlapping-speech and channel-routing limitations documented
rather than silently assumed away. Migration notes: `0004`. Tests: `test_idempotency.py`
plus the pipeline-specific assertions described in `AUDIO_PIPELINE.md`. Docs:
`AUDIO_PIPELINE.md` (dedicated stage-mapping document for this area specifically).

### Stage 6 — Calls workspace and call details
**Status: ✅ Complete.** Scope: call list (filter/paginate/status), upload UI, call
review screen (audio player synced to transcript synced to QA findings). Acceptance:
`tsc` clean, component tests pass, production build succeeds, manual walkthrough of
upload→review completed (see `WEB_PLATFORM.md`). Extended later with `CallInfoPanel`
(checksum/model-versions/channel metadata, section 8 pass). Tests:
`AudioPlayer.test.tsx`, `TranscriptPanel.test.tsx`. Docs: `WEB_PLATFORM.md`.

### Stage 7 — Scorecard builder and QA engine
**Status: ⚠️ Partial — stated plainly, not glossed over.** The **QA engine** half is
done: a modular, schema-validated rule-evaluation system
(`backend/pipeline/qa_engine/`) with two working rule types (keyword, semantic) and a
`RuleEvaluator` extension point for the rest, versioned scorecards
(`group_id`/`version`, immutable once published), idempotent re-evaluation. The
**scorecard builder** half — a no-code UI for authoring scorecards — was never built;
this was an explicit, agreed scope decision at plan-approval time (Phase 1 seeds one
example scorecard via `backend/scripts/seed_example_scorecard.py`, no admin UI exists
to create/edit scorecards through the product itself). This is Stage 10 territory
(administration) in this staging model and hasn't started. Tests:
`test_qa_engine.py`, `test_qa_evaluation_idempotency.py`. Docs: `MODULES.md`,
`WEB_PLATFORM.md`.

### Stage 8 — Human review workflow
**Status: ✅ Complete.** Scope: confirm/reject/correct/reopen on findings,
add/remove evidence, transcript and speaker-role correction, full audit trail.
Extended in the section 8 pass (`28c9dc3`) to make that trail actually queryable
(`GET /findings/{id}/history`, `GET /calls/{id}/utterances/{id}/history`), not just
stored. Acceptance: a reviewer's correction is preserved alongside the original AI
verdict, never overwrites it, and is attributable to a specific user and timestamp.
Tests: `test_explainability_history.py`. Docs: the "Data integrity & auditability"
section of `WEB_PLATFORM.md`.

### Stage 9 — Analytics and reporting
**Status: ❌ Not started.** Scope (from the approved plan's Phase 2+ roadmap):
aggregation views over `qa_evaluations`/`qa_findings` by agent/team/project/scorecard/
date/error-type, dashboard, drill-down from a chart to the underlying filtered call
list, CSV/Excel/PDF export. Explicit requirement carried forward from the approved
plan: this must be backed by real computed data (SQL views/materialized views), never
mocked static numbers. Not begun — no schema, no endpoints, no UI for this exists yet.

### Stage 10 — Administration and integrations
**Status: ❌ Not started.** Scope: admin console (users/roles/organizations/projects/
teams/agents/**scorecard authoring UI**/processing settings/model selection/storage-
retention config/audit-log viewer/system health/background-job views) and telephony
connector implementations (Voiso, Asterisk, SFTP, generic object storage/REST/webhook/
CSV import) against the `IngestionConnector` interface point already reserved
(`backend/pipeline/ingestion/base.py`, still an empty placeholder) and the
`ingestion_sources` table (schema exists, unused). Not begun.

### Stage 11 — Security hardening, observability, deployment, and acceptance testing
**Status: ⚠️ Partial.** Security hardening and observability are substantially done,
delivered as part of the sections 6/8/9 correction passes rather than a single
dedicated Stage 11 pass: structured JSON logging (`backend/app/logging_config.py`),
request logging, organization-boundary enforcement, file-size/rate limiting, audit
logging, the `AzureOpenAIModel`/privacy-leaking-`print` fixes (`SECURITY.md` has the
full list). Deployment configuration exists (`docker-compose.yml`, three Dockerfiles).
**Not done**: an actual `docker-compose up` run has never been executed in this
session — no Docker was available in the sandbox this was built in (see
`WEB_PLATFORM.md`'s "What was NOT run in this session"). Formal acceptance testing
(a documented sign-off checklist executed against a real running deployment, backup/
restore drill, a real pipeline run against actual audio through the GPU worker) has
not happened. This is the concrete, current blocker before Stage 11 — and therefore
Phase 1 as a whole — can be called genuinely done, not just code-complete.

## Forward plan

Stages 9 and 10 have defined scope above (inherited from the approved plan's
Phase 2+ roadmap) but no acceptance criteria/tests/migration plan drafted yet — that
drafting is the first step for either, not skipped straight to implementation, per
this section's own requirement. Stage 11's remaining item (real-environment
acceptance testing) is a prerequisite for confidently starting Stage 9/10 work on
top of the current foundation, not something to defer further.
