# Release, Upgrade, and Trust-Preserving Change Management

## Release Artifact (Machine-Verifiable)
A release is valid only when all fields below are defined and internally consistent at startup:
- `code_sha`: immutable code identifier (`VERSION_HASH`/`GIT_SHA`)
- `expected_alembic_head`: expected database migration head (optional but enforced when set)
- `supported_api_versions`: explicit contract versions (`RELEASE_SUPPORTED_API_VERSIONS`)
- `enabled_feature_flags`: explicit feature flag list (`RELEASE_FEATURE_FLAGS`)
- `signing_mode`: one of `required | optional | disabled`
- `signing_required`: boolean control (`SIGNING_REQUIRED`)

Startup records this release artifact in `app.startup` system event payload.

## Startup Guards (Fail-Closed)
Startup refuses to run when any guard fails:
- alembic head mismatch (when expected head configured)
- invalid signing mode or invalid signing configuration combination
- unsupported `RELEASE_SUPPORTED_API_VERSIONS`
- production unsafe combinations:
  - `ENV=prod` with `LOG_LEVEL=DEBUG`
  - `ENV=prod` with `AUTO_CREATE_SCHEMA=true`
  - required production secrets/config missing
  - unsigned operation in prod without explicit `SIGNING_MODE=disabled`

Unsigned modes are never implicit:
- `SIGNING_MODE=disabled` is explicit and logged
- optional unsigned mode is logged

## Migration Discipline
Migration rules:
- forward-only migration discipline
- never edit an applied migration
- rerun-safe migrations only
- pre-check and post-check required

Pre-migration checks:
- confirm target release `code_sha`
- confirm current `alembic current`
- confirm target `alembic heads`
- verify backup restore point exists

Post-migration checks:
- verify `alembic current` equals target head
- start app and verify readiness
- run proof and lineage verification sample

Rollback strategy:
- prefer roll-forward corrective migration
- if app rollback needed, use app artifact compatible with current DB head
- database rollback only by approved procedure with proof-chain integrity verification

Do not:
- downgrade blindly after cryptographic schema-affecting changes
- edit migration files in-place

## Upgrade Procedure (Human-Executable)

### Staging Upgrade
- export current environment values used by startup guards
- set release vars:
  - `VERSION_HASH`
  - `EXPECTED_ALEMBIC_HEAD`
  - `RELEASE_SUPPORTED_API_VERSIONS`
  - `RELEASE_FEATURE_FLAGS`
  - `SIGNING_MODE`
- run migrations: `alembic upgrade head`
- start service with target artifact
- verify:
  - `/health` is alive
  - `/ready` is ready
  - startup event includes release artifact
- execute full test suite gate from repository runbook
- run offline verification samples for existing proofs

Abort conditions:
- readiness fails
- startup guard failure
- verification mismatch on existing proofs
- migration head mismatch

### Production Upgrade
- confirm staging success and release approval
- confirm backup/restore point
- apply migrations: `alembic upgrade head`
- deploy target artifact with release vars
- verify `/ready` and startup release event
- verify representative existing proofs unchanged
- monitor integrity/security counters for regression

Safe abort:
- stop traffic to faulty instances
- redeploy previous app version compatible with current DB head
- do not rewrite or backfill cryptographic history

Partial failure detection:
- startup loops with guard failures
- mixed `code_sha` across instances
- inconsistent alembic head between nodes
- proof verification result drift for historical artifacts

## Change Classification Policy

### Non-Breaking (Safe)
- internal refactor with unchanged external behavior
- logging/observability additions without contract changes
- documentation updates

### Additive (Safe)
- new endpoints or fields that do not change existing behavior
- new optional headers/metadata
- new migration adding nullable/additive structures

### Breaking (Requires New API Version)
- response envelope shape changes
- stable error code mapping changes
- pagination contract changes
- idempotency conflict semantics/status changes
- auth/signature header contract changes

Enforcement:
- v1 frozen contract tests must pass
- changes that alter v1 snapshot require new API version and new snapshot/tests

## Trust-Preservation Requirements During Change
Any release is invalid if it:
- modifies or rewrites append-only historical records
- changes historical key bindings
- changes verification outcomes for existing valid proofs

Upgrade acceptance requires:
- historical proof verification results remain unchanged
- lineage verification results remain unchanged
- anchor verification remains unchanged
