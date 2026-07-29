# Security — Section 9 Audit

Section 9 of the product spec lists mandatory security design elements. This audits
each one against the actual implementation — what was already correct, what was a real
gap fixed in this pass, and what's a deliberate scope decision (documented, not
silently skipped).

## Already correct (confirmed by inspection, not assumed)

- **Secure authentication** — JWT access token (short-lived) + httpOnly refresh cookie
  with server-side rotation/revocation (`backend/app/routers/auth.py`,
  `refresh_tokens` table). A replayed refresh token is usable exactly once before
  rotation invalidates it.
- **Password hashing** — argon2id (`passlib[argon2]`), not a legacy/weak scheme.
- **Permission checks** — every router endpoint depends on `require_permission(code)`
  (`backend/app/dependencies.py`), which enforces server-side against a
  `role_permissions` matrix. The frontend's `ProtectedRoute`/hidden buttons are UX
  only and were never relied on for enforcement.
- **Safe filenames / protection from path traversal** — `AudioStorage.save()`
  (`backend/pipeline/storage.py`, both `LocalFilesystemStorage` and
  `S3CompatibleStorage`) never uses the client-supplied filename to build a storage
  path. The storage key is always `f"{call_id}{ext}"` where `call_id` is a
  server-generated UUID and `ext` is `Path(filename).suffix` — `.suffix` never returns
  path separators regardless of what the client sends (e.g. a filename of
  `"../../../etc/passwd"` yields `ext == ""`, not a traversal). The original,
  untrusted filename is stored only as a display string (`Call.original_filename`),
  never used to construct a filesystem or S3 path.
- **Secret management** — `.env`-based (gitignored; `.env.example` has no real
  secrets). Section 6's audit already fixed the one real gap here (`JWT_SECRET_KEY` had
  a hardcoded fallback — now has no default, app refuses to start without it).
- **CORS** — `CORSMiddleware` restricted to explicit configured origins
  (`Settings.cors_origins`), never `"*"`.

## Real gaps found and fixed in this pass

- **Organization isolation had zero enforcement.** Every `Call`/`Speaker`/`Utterance`/
  `QAFinding` row already carries (or is reachable via) `org_id`, but
  `get_call_or_404` and the finding/utterance lookups only checked existence, not
  ownership — any authenticated user could fetch any call, stream any call's audio, or
  read any finding's history by ID, regardless of organization. Multi-tenancy isn't
  "enabled" today (confirmed single-org deployment), which is the literal reading of
  "isolation if multi-tenancy is enabled" — but shipping zero enforcement now means it
  would need to be retrofitted under pressure the day a second organization is ever
  created, and every table was already designed to support that. Fixed:
  `get_call_or_404` (`dependencies.py`) and `_get_finding_or_404` (`findings.py`, via a
  join through `qa_evaluations.call_id`) now require and check `org_id`, 404ing (never
  403) across an org boundary so the response doesn't confirm the resource exists
  elsewhere. Covered by `test_org_isolation.py`.
- **No file-size restriction.** A client could upload an arbitrarily large file with
  no limit anywhere. Fixed in two layers: `app/main.py`'s
  `reject_oversized_uploads` middleware rejects an honest `Content-Length` over
  `Settings.max_upload_size_bytes` (default 500MB) before the body is read; a post-save
  check in `call_service.py` catches a missing/wrong `Content-Length` and deletes the
  already-written file rather than leaving it orphaned. **Neither stops a client that
  lies about `Content-Length` and streams more anyway** — that needs a reverse-proxy
  limit (e.g. nginx `client_max_body_size`), and this repo's `docker-compose.yml`
  exposes the `api` service directly with no reverse proxy in front of it. Add one
  before treating the app-level check as sufficient in a hostile-network deployment.
- **Audit logging was incomplete.** `AuditLog`/`ReviewAction` covered login (success),
  speaker-role corrections, and QA review actions, but not upload, reprocess, cancel,
  or **failed** login attempts — the last of which matters most for detecting
  brute-force/credential-stuffing attempts. Fixed: `call_uploaded`,
  `call_reprocess_requested`, `call_cancelled`, and `login_failed` are now all
  recorded. A failed login for a nonexistent email is logged (structured, JSON) but not
  written to `audit_log` (there's no org to attach it to); a failed login for a real
  account is both logged and audit-logged against that account's org.
- **Privacy-unaware logs — a real, active leak, not a hypothetical one.**
  `src/text/llm.py::LLMOrchestrator.generate()` (unmodified until now) had an
  unconditional `print(response)` — the LLM's raw response to every single
  Classification/SentimentAnalysis/Summary/etc. call, which is derived directly from
  customer-conversation content, printed to stdout on every call processed. In this
  platform's own Docker/systemd deployment, that's captured straight into container
  logs — directly contradicting "privacy-aware logs" and undermining the entire
  local-first/privacy premise from section 3. Fixed: the print statement is removed
  (see the inline comment for why); `LLMResultHandler.log_result` (which prints the
  **full call transcript** — not currently called anywhere in this platform's pipeline,
  but a reachable public method) now logs at `DEBUG` level through the structured
  logger instead of printing unconditionally, so it's opt-in-visible, not automatic.
  Also checked: `llm_schemas.py`'s malformed-item warnings log the offending raw item
  for debugging — acceptable here since it only fires on a validation *failure* on
  fields with a small, fixed shape (`index`/`sentiment`/`profane`/etc.), not the
  transcript content itself.
- **No rate limiting beyond login.** Added a `30/minute` limit on `POST /calls`
  (upload) — an authenticated-but-abusable endpoint that consumes real storage and
  eventually GPU processing time per request.

## Deliberate scope decisions (not gaps — stated explicitly, not silently skipped)

- **CSRF strategy.** The refresh-token cookie is `SameSite=Strict` (see
  `_set_refresh_cookie`, `routers/auth.py`) — a cross-site request simply never carries
  the cookie under strict mode, which is a complete mitigation for the classic
  cookie-riding CSRF attack (an attacker's page can't get the victim's browser to send
  it at all, not just "the server would reject it"). The access token is a Bearer
  header the frontend attaches explicitly in JS (`api/client.ts`), which a cross-site
  page cannot read or forge regardless of cookies. No separate CSRF token is used
  because none of this API accepts session-cookie-only authentication anywhere — this
  is the appropriate strategy for a Bearer+SameSite-cookie API, not the same one a
  server-rendered cookie-session app would need.
- **Retention and deletion policy.** `Call.retention_expires_at` is set at upload time
  from `Settings.default_retention_days` (default `None` — retention disabled by
  default, since a retention *duration* is a compliance/business decision this
  platform shouldn't default on an operator's behalf). Enforcement is
  `backend/scripts/purge_expired_calls.py` (`--dry-run` supported), invoked manually or
  via an external cron — deliberately **not** an automatic Celery Beat schedule yet
  (see the script's docstring: deleting recordings shouldn't silently start happening
  the moment a retention setting is added to `.env`, before an operator has seen a
  dry-run). The script deletes only the **audio file** (`AudioStorage.delete` +
  `Call.deleted_at`) — it never touches utterances/findings/review history, because
  section 8 requires historical QA reports stay explainable indefinitely, which is a
  different lifecycle than "how long do we keep the raw recording." `GET
  /calls/{id}/audio` returns `410 Gone` (not a crash) for a purged call while
  `GET /calls/{id}` continues to return full transcript/QA history.
- **Backup and restore.** Not code — an operational runbook, stated here since nothing
  else in the repo covers it:
  - **Postgres**: `pg_dump`/`pg_restore` (or continuous WAL archiving for
    point-in-time recovery) against the `postgres` service/volume in
    `docker-compose.yml`. This is the system of record for everything except audio
    bytes — users, calls, transcripts, QA findings, review history, audit log.
  - **Audio storage**: for `STORAGE_BACKEND=local`, back up the `audio_storage` Docker
    volume (or its host bind-mount) directly. For `STORAGE_BACKEND=s3`, rely on the
    object store's own durability/versioning (S3 versioning or MinIO's
    equivalent) rather than a separate backup process.
  - **Restore drill**: not yet exercised end-to-end in this repo — flagged as a
    Phase 2 action item (a scripted restore-and-verify runbook), not claimed as done.
- **Project/team-scoped authorization** (beyond org isolation) — e.g. restricting a
  Team Leader to only their own team's calls — is not implemented. `require_permission`
  checks role-level permission codes, not per-resource team/project membership. This is
  a product/RBAC-model feature (fine-grained ACLs), reasonably deferred to Phase 2
  alongside the admin console, and distinct from the organization-boundary fix above
  (which is a hard security boundary, not a convenience filter).
