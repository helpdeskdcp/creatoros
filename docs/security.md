# Security

## Authentication

- Passwords hashed with bcrypt (via `passlib`), never stored or logged in
  plaintext.
- JWT access tokens (short-lived, default 15 min) + refresh tokens
  (30 days, httpOnly cookie, rotated on every use — reusing a revoked
  refresh token is rejected, see `test_refresh_rotates_token_and_old_refresh_fails`).
- Refresh tokens are never stored raw: `sessions.refresh_token_hash` is a
  SHA-256 hash of the token's random component; a database leak doesn't
  yield usable tokens.

## Authorization (RBAC)

Five roles: `OWNER > ADMIN > EDITOR > ANALYST > VIEWER`. Enforced via
FastAPI dependencies (`app/modules/auth/dependencies.py:require_roles`),
never by client-side checks. The first user to register becomes `OWNER`;
every subsequent registration defaults to `VIEWER` until an admin promotes
them (`PATCH /api/v1/users/{id}/role`).

## Secrets at rest

- `oauth_access_token_encrypted` / `oauth_refresh_token_encrypted` on
  `channels` are encrypted with Fernet (`app/core/crypto.py`) using
  `ENCRYPTION_KEY`, never stored in plaintext.
- `.env` is gitignored; `.env.example` contains only placeholders.
- `audit_logs` writes go through `app/modules/audit/service.py:record()`,
  which actively scrubs any field whose key matches
  `token|secret|password|api_key|authorization` before writing — a
  careless caller cannot leak a credential into the audit trail even by
  accident.

## Input validation

Every request body is a Pydantic v2 schema with explicit types and
constraints (e.g. `password: str = Field(min_length=10)`). SQLAlchemy's
query builder is used throughout — no raw string SQL interpolation
anywhere in the codebase, which is the primary SQL-injection defense.

## Transport / API hardening

- CORS is restricted to `CORS_ORIGINS` (comma-separated allow-list), not
  `*`.
- Every response error follows one shape
  (`{"error": {"code", "message", "request_id"}}`) so the frontend never
  has to guess at error structure, and internal exception details never
  leak to the client (`app/core/errors.py:unhandled_exception_handler`
  returns a generic message; the real traceback only appears in
  server-side structured logs).
- Structured JSON logging includes a `request_id` propagated via
  `X-Request-ID`, correlating a client-visible error with server logs
  without exposing internals to the client.

## Publishing safety (Growth OS)

Automated publishing is the highest-risk surface in this system (it can
take an irreversible, externally-visible action — uploading a video). It
is protected by:

1. A 13-step safety gate (`app/modules/publishing/service.py:run_safety_gate`)
   checking, in order: channel ownership, OAuth token presence, publishing
   mode match, autonomous-mode explicit enablement, rule expiry, kill
   switch state, daily rate limit, metadata completeness/validity,
   thumbnail presence, and minimum content/subscriber score thresholds.
2. Idempotency: `publishing_runs.idempotency_key` is unique — a retried
   request (Celery retry, duplicate client submission) can never create a
   second upload for the same intent.
3. A creator-controlled kill switch (`app/jobs/kill_switch.py`) — checked
   by the safety gate before any `AUTHORIZED_AUTONOMOUS` action. Stopping
   automation never cancels in-flight work and never deletes data.
4. Every gate evaluation (pass or fail) is recorded in
   `publishing_attempts` and mirrored into `audit_logs` — there is no
   silent path from "creator connected a channel" to "video published"
   that isn't logged.

## Known limitations / accepted risk

- **Frontend dependency scan**: `npm audit` reports 4 remaining
  vulnerabilities after pinning Next.js to the latest patched 15.5.x —
  all four are in **build-time-only** tooling (`postcss@8.4.31` bundled
  *inside* `next`'s own build pipeline, and `vitest`/`vite`/`esbuild`,
  which are dev-time test-runner dependencies never included in the
  production Docker image). None are reachable from a request a real user
  sends to the running application. Closing the `next`-internal postcss
  pin fully requires Next.js 16, which has no stable release as of this
  writing — tracked in `docs/ROADMAP.md` rather than adopting a
  pre-release major version in a "production-grade" app.
- **CSRF**: the refresh-token cookie is `SameSite=Lax`, which mitigates
  (but combined with the JWT-in-header pattern for all authenticated
  requests, effectively eliminates) CSRF risk on state-changing endpoints,
  since a cross-site request cannot attach a valid `Authorization` header.
  No separate CSRF token is issued. Revisit if cookie-only auth is ever
  introduced for a new client.
- **Rate limiting**: per-endpoint rate limiting (beyond the YouTube
  provider's own retry/backoff and the publishing daily-limit rule) is not
  yet implemented at the API gateway level. Nginx can be configured with
  `limit_req` if this becomes necessary before a WAF/CDN is placed in
  front of production.

## Reporting a vulnerability

This is a development-stage project; there is no public disclosure process
yet. Treat any credential or vulnerability discovery as you would for
internal-only software until a formal process exists.
