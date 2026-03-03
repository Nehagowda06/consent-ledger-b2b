# Operator Runbook

## Purpose and Scope
This runbook defines human-executable procedures for operating, recovering, and auditing the API safely under normal and incident conditions.

This document is for on-call operators and responders who did not build the system.

Use this runbook when:
- starting or stopping the service
- validating deployment health
- responding to outages or integrity/security alerts
- handling audit or regulator requests

## Preconditions
Before acting, confirm:
- You have shell access to the deployment environment.
- You have access to deployment environment variables management.
- You can run database read queries and migration status commands.
- You can access service logs and health endpoints.
- You can run offline verification tools from a trusted workstation.

Do not proceed if any precondition is missing. Escalate immediately.

## Safety Rules
Always follow these rules:
- Do not modify historical data tables manually.
- Do not edit applied Alembic migrations.
- Do not regenerate, overwrite, or backfill cryptographic history.
- Do not run ad-hoc SQL UPDATE/DELETE on append-only ledgers.
- Do not rotate signing identity material without an approved rotation plan.
- Do not disable authentication or rate limiting for troubleshooting.

If uncertain, stop and escalate.

## Normal Operations

### Start the System
Symptoms/Trigger:
- Planned startup, deploy, or restart.

Procedure:
- Confirm required environment is set for target environment.
- Confirm database is reachable from the service host.
- Confirm migration status before process start.
- Start service process using deployment command (no reload in production).
- Wait for process startup logs.

Verify:
- `GET /health` returns process alive.
- `GET /ready` returns ready with all required checks passing.
- Startup logs include environment, version hash, and migration head.

What not to do:
- Do not start production with missing required secrets.
- Do not enable debug/reload in production.
- Do not force-start after readiness failure.

Safe actions:
- Roll back deployment if readiness does not pass.
- Escalate if migration head mismatch persists.

### Stop the System Safely
Symptoms/Trigger:
- Planned maintenance, deploy rollback, or controlled shutdown.

Procedure:
- Announce maintenance window if required.
- Stop traffic routing to the instance (drain).
- Send graceful termination signal.
- Wait for process shutdown completion.
- Confirm background worker stopped.

Verify:
- Process exits cleanly.
- No new writes accepted.
- No stuck worker loops continue.

What not to do:
- Do not hard-kill before graceful timeout unless emergency containment is required.

Safe actions:
- If graceful stop stalls, capture diagnostics, then force stop.

### Verify Readiness
Symptoms/Trigger:
- Post-start verification or periodic health check.

Procedure:
- Call `GET /ready`.
- Inspect each readiness check result.

Ready only if:
- database connectivity check passes
- migration head check passes when configured
- signing material check passes when signing required
- worker state matches configuration

What not to do:
- Do not ignore partial readiness failures.

Safe actions:
- Treat any failed readiness check as not deployable.

### Verify Integrity Signals
Symptoms/Trigger:
- Routine integrity review, pre-release validation, or post-incident confirmation.

Procedure:
- Inspect structured logs for security/invariant failures.
- Review system event ledger entries for failure and denial events.
- Run offline verification for lineage/proof artifacts as needed.

Verify:
- No unexplained spikes in verification failures.
- No append-only violation attempts without tracked incident.
- Correlation IDs link external failures to system events.

What not to do:
- Do not clear logs/ledger to hide failures.

Safe actions:
- Open incident if integrity failure signals are sustained.

## Incident Response

### Incident: Database Unavailable
Symptoms:
- readiness db check fails
- elevated 5xx errors
- operation failure class `db.unavailable`

What to check:
- database service status
- network path/firewall
- credential validity
- connection pool exhaustion

What not to do:
- Do not disable DB checks.
- Do not switch to unsafe fallback storage.

Safe actions:
- Restore DB connectivity.
- Keep API fail-closed until DB healthy.
- Re-validate readiness before restoring traffic.

### Incident: Migration Mismatch
Symptoms:
- readiness migration check fails
- startup fails with expected vs actual head mismatch

What to check:
- deployed app version
- configured expected head
- actual `alembic heads`

What not to do:
- Do not edit migration files already applied.
- Do not bypass head validation in production.

Safe actions:
- Apply correct forward migration set for deployed version, or
- roll back app to version matching current DB head.

### Incident: Signing Failure
Symptoms:
- signature verification failure metrics increase
- proof/lineage signature checks failing

What to check:
- signing key material presence and format
- signer fingerprint/public key consistency in artifacts
- recent key rotation/change events

What not to do:
- Do not regenerate historical signatures.
- Do not rewrite existing signed artifacts.

Safe actions:
- Contain by pausing operations requiring valid new signatures if policy requires.
- Validate whether failures are input tampering vs configuration drift.
- Escalate for security review.

### Incident: Repeated Verification Failures
Symptoms:
- sustained offline verification failures
- failure reasons indicate chain mismatch/anchor mismatch

What to check:
- artifact source authenticity
- transport corruption
- potential data tampering indicators

What not to do:
- Do not mark failures as false positives without evidence.
- Do not alter ledger rows to force verification pass.

Safe actions:
- Preserve evidence (artifacts, logs, request IDs, timestamps).
- Trigger tampering investigation.
- Notify security and compliance owners.

### Incident: Suspected Tampering
Symptoms:
- hash-chain mismatch
- anchor mismatch
- unexplained append-only violation attempts

What to check:
- timeline of system events
- deployment/change events around first failure
- database access/audit logs

What not to do:
- Do not continue normal writes until containment decision is made.
- Do not delete suspicious rows.

Safe actions:
- Activate incident response process.
- Preserve immutable evidence.
- Shift system to containment posture per policy.

### Incident: Tenant Abuse or Compromise
Symptoms:
- suspicious traffic patterns
- repeated auth failures/rate-limit events
- confirmed key compromise

What to check:
- affected tenant identifiers
- API key usage and revocation state
- write attempts and endpoint targets

What not to do:
- Do not disable global auth controls.
- Do not expose tenant data during triage.

Safe actions:
- revoke compromised tenant keys
- disable/suspend tenant if required by policy
- issue replacement keys through admin controls
- preserve all related audit/system events

## Recovery and Rollback

### Restore from Database Backup
Goal:
- recover service while preserving cryptographic trust chains.

Procedure:
- Identify last known good backup with verified integrity.
- Restore backup to isolated environment first.
- Verify migration head compatibility with intended app version.
- Run integrity verification on restored data.
- Promote restore only after verification passes.

What not to do:
- Do not perform partial table restore for append-only ledgers unless formally approved and fully documented.

Safe actions:
- Prefer full-point-in-time recovery over selective edits.

### Restore Without Breaking Proofs
Procedure:
- Keep historical ledger and lineage rows byte-for-byte intact.
- Keep identity public keys/fingerprints intact.
- Preserve ordering and timestamps as stored.
- Validate offline proofs against restored data.

Trust invalidation triggers:
- missing or altered chain events
- changed historical hashes
- replaced identity key bindings

### Redeploy With Same Identity Keys
Procedure:
- Ensure signing private key material is supplied exactly as expected.
- Ensure corresponding public key/fingerprint binding is unchanged.
- Start service and validate readiness.
- verify new outputs can be validated by existing offline verifiers.

What invalidates trust:
- deploying with different signing key while claiming continuity without delegation/rotation evidence.

## Key and Secret Rotation

### Admin Key Rotation
Preserves historic validity:
- yes, if performed by replacing runtime secret and validating admin access continuity.

Procedure:
- provision new admin key in secret manager/env
- deploy/restart service
- verify admin endpoints with new key
- revoke old admin key material in secret store

Forbidden:
- storing admin key in code or repository

### Signing Key Rotation
Preserves historic validity:
- yes, if old public identity remains in history and new signatures are attributable under approved trust model.

Procedure:
- generate new signing keypair offline
- register public key identity per approved process
- deploy new private key material securely
- verify signatures from new key
- keep historical artifacts unchanged

Forbidden:
- re-signing historical records
- deleting old identity records to hide rotation

### Webhook Secret Rotation
Preserves historic validity:
- yes, for future deliveries; does not alter historical proofs.

Procedure:
- issue new endpoint secret
- update receiver verification configuration
- validate signed delivery acceptance
- revoke old secret material

Forbidden:
- exposing raw secrets in logs/tickets

### Rotations That Are Forbidden
- any rotation that rewrites historical signed artifacts
- any rotation that changes historical public-key fingerprints retroactively
- any rotation that requires deleting append-only history

## Audit and Verification

### Export System Ledger
Procedure:
- use admin export capability for system ledger/proofs
- store exported artifact in immutable case folder
- record export timestamp and request ID

What not to do:
- do not redact or edit exported hashes

### Export Proofs
Procedure:
- export required proof bundle(s) from tenant-scoped endpoints
- confirm cache-control/no-store behavior at retrieval time
- archive original JSON unchanged

### Offline Verification
Procedure:
- use trusted offline verifier environment
- run verification on exported artifacts only
- record verifier output (verified/failure reason/failure index)
- repeat verification from second trusted environment for critical cases

### Respond to External Audit Requests
Procedure:
- collect requested artifacts (ledger export, proofs, verification outputs)
- provide immutable copies and verification instructions
- provide correlation IDs and event timestamps
- avoid sharing secrets or internal credentials

What not to do:
- do not provide database credentials
- do not provide private keys

## Guarantee Boundaries

The system guarantees:
- append-only cryptographic history where implemented
- deterministic offline verification for exported artifacts
- fail-closed behavior on critical integrity/auth checks
- traceable correlation via request IDs and system events (best-effort event recording)

The system does not guarantee:
- prevention of all operator misuse outside enforced controls
- recovery of trust if historical cryptographic records are destroyed
- correctness of external systems that consume webhooks/proofs

Irreversible actions:
- deleting append-only ledger/history rows
- losing signing private key without approved transition path
- altering historical hash-linked data

Actions that permanently destroy trust:
- rewriting historical events/proofs
- replacing identity bindings retroactively
- restoring inconsistent partial data sets that break chain continuity

## Final Health Validation Checklist
System is healthy if and only if all statements below are true:
- Liveness endpoint returns healthy.
- Readiness endpoint returns ready with no failed checks.
- Expected migration head matches actual head when configured.
- Required signing material is present when signing is required.
- Worker state matches configured expectation.
- No active, unexplained spikes in verification failure metrics.
- No unresolved append-only violation attempts.
- Recent externally visible failures include deterministic error codes and request IDs.
- System event ledger is queryable and reflects current operational failures/denials.
- Offline verification succeeds for sampled recent artifacts.
- No emergency bypasses or insecure overrides remain enabled.