# Consent Ledger API

FastAPI service for tenant-scoped consent management, idempotent writes, and webhook delivery.

## Environment Variables

Set these before running the API:

- `DATABASE_URL`:
  - Required in `prod`
  - In `dev`, falls back to `postgresql+psycopg://postgres@localhost:5433/consent_ledger`
- `ENV`:
  - `dev` (default) or `prod`
- `API_KEY_HASH_SECRET`:
  - Required in `prod`
  - In `dev`, an insecure fallback is used with warning
- `WEBHOOK_SIGNING_SECRET`:
  - Required in `prod`
  - In `dev`, an insecure fallback is used with warning
- `WEBHOOK_WORKER_ENABLED`:
  - `false` by default
- `WEBHOOK_MAX_ATTEMPTS`:
  - `8` by default
- `CORS_ALLOWED_ORIGINS`:
  - Comma-separated origins
  - In `dev`, defaults to:
    - `http://localhost:3000`
    - `http://127.0.0.1:3000`
  - In `prod`, defaults to empty (deny)
- `AUTO_CREATE_SCHEMA`:
  - `false` by default
  - If `true` and `ENV=dev`, startup will run `Base.metadata.create_all` for local quick-start only

## Run Migrations

```powershell
cd apps/api
venv\Scripts\alembic upgrade head
```

## Production Migrations (Manual/CI Step)

Run migrations before starting the API container/process:

```bash
alembic upgrade head
```

Do not rely on app startup to run migrations.

## Create Tenant + API Key

```powershell
cd apps/api
venv\Scripts\python scripts\create_tenant_key.py --use-default-tenant-id
```

The script prints the plaintext API key once. Only hashes are stored.

## Run API

```powershell
cd apps/api
venv\Scripts\uvicorn main:app --reload --port 8000
```

## Production Startup Command

Use uvicorn without reload:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Docker (Production)

Build:

```bash
docker build -t consent-ledger-api:latest .
```

Run:

```bash
docker run --rm -p 8000:8000 \
  -e ENV=prod \
  -e DATABASE_URL="postgresql+psycopg://user:pass@db:5432/consent_ledger" \
  -e API_KEY_HASH_SECRET="replace-with-strong-secret" \
  -e WEBHOOK_SIGNING_SECRET="replace-with-strong-secret" \
  -e CORS_ALLOWED_ORIGINS="https://your-frontend.example" \
  -e WEBHOOK_WORKER_ENABLED=false \
  consent-ledger-api:latest
```

## Health Check (Liveness)

Unauthenticated liveness endpoint (no DB dependency):

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

Readiness endpoint (fail-closed):

```bash
curl http://127.0.0.1:8000/ready
```

Readiness checks include:
- `db` connectivity
- `migration_head` match when `EXPECTED_ALEMBIC_HEAD` is configured
- `signing_material` when `SIGNING_REQUIRED=true`
- `webhook_worker` state when `WEBHOOK_WORKER_ENABLED=true`

## Observability Signals

Structured counters are emitted for invariant and security events:

- `security.signature_verification_failed`
- `security.delegation_verification_failed`
- `security.tenant_write_denied`
- `security.rate_limit_enforced`
- `security.append_only_violation_attempt`
- `runtime.unexpected_exception`

Externally visible failures include:
- stable error envelope with deterministic `error.code`
- `X-Request-Id` correlation header
- best-effort `system_event_ledger` event for incident correlation

## API Contract

Success envelope:

```json
{ "data": {} }
```

Error envelope:

```json
{
  "error": {
    "code": "STABLE_CODE",
    "message": "Human readable message",
    "request_id": "uuid"
  }
}
```

Stable error codes are defined in `core/contracts.py` and documented for integrators in:

- `docs/PORTAL_INTEGRATION_GUIDE.md`

## API Versioning Guarantees

The external contract is frozen in code under `core/contracts.py`:

- Version header: `X-API-Version`
- Current supported version: `v1`
- Default version is explicit: `v1`
- Unsupported versions return deterministic `400` with stable error envelope

Compatibility guarantees:

- `v1` envelopes (`success`, `error`, `pagination`) are frozen
- `v1` auth/idempotency/webhook signing header semantics are frozen
- Breaking changes require a new version (for example `v2`)
- Existing `v1` behavior must remain compatible; contract tests enforce this

Forbidden under `v1`:

- Changing envelope field names
- Changing error envelope keys
- Changing pagination keys
- Changing idempotency mismatch status from `409`

## Pagination Contract

List endpoints use:

- `limit` (default `50`, max `100`)
- `offset` (default `0`)

List response format:

```json
{
  "data": [],
  "meta": {
    "limit": 50,
    "offset": 0,
    "count": 123
  }
}
```

## Run Tests (Windows, virtualenv-safe)

Use the helper so tests always run with `apps/api/venv` packages:

```powershell
cd apps/api
.\run_tests.ps1
```

Run a specific module:

```powershell
.\run_tests.ps1 tests.test_auth
```

## Authenticated Request Examples

`Authorization` uses Bearer API key.

### cURL (with Idempotency-Key)

```bash
curl -X PUT "http://127.0.0.1:8000/consents" \
  -H "Authorization: Bearer clb2b_xxx" \
  -H "Idempotency-Key: 11f8bd5a-30aa-460b-8c3d-9f7f6c5639a4" \
  -H "Content-Type: application/json" \
  -d "{\"subject_id\":\"user_123\",\"purpose\":\"marketing_emails\",\"status\":\"ACTIVE\"}"
```

### PowerShell (with Idempotency-Key)

```powershell
$headers = @{
  Authorization = "Bearer clb2b_xxx"
  "Idempotency-Key" = "11f8bd5a-30aa-460b-8c3d-9f7f6c5639a4"
  "Content-Type" = "application/json"
}
$body = @{
  subject_id = "user_123"
  purpose = "marketing_emails"
  status = "ACTIVE"
} | ConvertTo-Json

Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8000/consents" -Headers $headers -Body $body
```

## Portal Integration Guide

See `docs/PORTAL_INTEGRATION_GUIDE.md` for:

- Tenant onboarding flow
- Upsert/revoke lifecycle
- API key rotation flow
- Webhook verification
- Error handling guidance

## Production Migration Strategy

1. Apply migrations before deploying new application code:
   - `cd apps/api`
   - `venv\Scripts\alembic upgrade head`
2. Run migrations as a release/CI job, not from app import/startup.
3. Verify revision state:
   - `venv\Scripts\alembic heads`
   - Confirm deployed revision matches expected release revision.
4. Rollback guidance:
   - Identify prior revision id from `alembic history`.
   - Roll back one or more revisions intentionally, for example:
     - `venv\Scripts\alembic downgrade -1`
     - or `venv\Scripts\alembic downgrade <previous_revision_id>`
5. Rule:
   - Never edit a migration that has already been applied in any environment.
   - Use a new forward migration for fixes.

## Production Release Checklist

- [ ] Confirm required env vars are set:
  - `ENV=prod`
  - `DATABASE_URL`
  - `API_KEY_HASH_SECRET`
  - `WEBHOOK_SIGNING_SECRET`
  - `ADMIN_API_KEY`
  - `CORS_ALLOWED_ORIGINS` (explicit, non-empty in prod)
  - `API_KEY_RATE_LIMIT_PER_MIN` (> 0)
  - `EXPECTED_ALEMBIC_HEAD` (recommended for startup guard)
- [ ] Validate secrets rotation status:
  - rotate `API_KEY_HASH_SECRET` per policy
  - rotate `WEBHOOK_SIGNING_SECRET` per policy
  - rotate `ADMIN_API_KEY` per policy
  - ensure no secrets are committed or logged
- [ ] Rate limit sanity check:
  - confirm `API_KEY_RATE_LIMIT_PER_MIN` is production-appropriate
  - verify 429 behavior in a staging smoke test
- [ ] Webhook worker enablement:
  - set `WEBHOOK_WORKER_ENABLED=true` only when worker processing is intended
  - verify worker lifecycle logs on startup/shutdown
- [ ] Health endpoint verification:
  - `curl http://<host>:8000/health`
  - expect `{"status":"ok"}`
- [ ] Migration/deploy sequencing:
  - run `alembic upgrade head`
  - deploy app image after migration success
  - confirm startup logs include env, version hash, and migration head
- [ ] Rollback plan prepared:
  - previous app image/tag identified
  - previous alembic revision id identified
  - owner and communication channel for rollback approved

## Optional External Anchoring

External anchoring is an optional audit feature that publishes a digest of current tenant anchors.
It helps prove historical integrity even against privileged operator tampering by letting third parties
independently verify published digests later.

- Snapshot source:
  - Admin calls `POST /admin/anchors/snapshot`
  - Response includes sorted anchor list + digest
- Verification:
  - Anyone can call `POST /anchors/verify` with a snapshot
  - Verification is fully offline-capable and requires no DB access
- Optional commit hook:
  - Set `EXTERNAL_ANCHOR_COMMIT_PATH=/path/to/anchor_commits.log`
  - Each snapshot appends one line: `RFC3339 | digest`
  - If unset (default), no file writes occur

Suggested public publishing methods:
- commit digests to a public Git repository
- publish digests to a public notice board/status page
