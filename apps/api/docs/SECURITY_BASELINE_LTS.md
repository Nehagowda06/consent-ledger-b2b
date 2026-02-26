# Security Baseline (LTS)

This baseline is frozen for long-term support. Any change below is a security-breaking change and requires a major version decision.

## Frozen Guarantees

- Append-only ledgers remain append-only:
  - consent lineage
  - system event ledger
  - identity keys and delegations
  - signed assertions
- Tenant isolation is mandatory for tenant-authenticated APIs and data access.
- Production startup is fail-closed when required secrets are missing.
- Offline verification remains deterministic and does not require DB access.
- Verification failure ordering is security-significant:
  - signature failures are surfaced before structural/hash mismatch when signature material is present.
- Canonical serialization is stable:
  - sorted keys
  - no whitespace separators
  - UTF-8 encoding
- Hash outputs remain SHA-256 lowercase hex (64 chars) for all frozen verification surfaces.
- Public verification endpoints enforce body size limits and strict JSON parsing.
- Idempotency key parsing enforces deterministic validation and rejection rules.

## Frozen Public Behaviors

- `POST /lineage/verify` remains public and read-only.
- `POST /proofs/verify` remains public and read-only.
- `POST /anchors/verify` remains public and read-only.
- `POST /system/verify` remains public and read-only.
- Payload limit for each public verification endpoint remains `262144` bytes.
- Idempotency key max accepted length remains `255` bytes.

## Frozen Failure Semantics

- Malformed/unsafe idempotency keys are rejected with deterministic `400` behavior.
- Invalid system proof payload hashes are classified as `invalid payload_hash`.
- Signed proof/signature mismatch surfaces signature-oriented failure reasons.

## Breaking Security Change Definition

Any of the following is a breaking security change:

- Making append-only paths mutable.
- Changing canonicalization without major versioning and migration strategy.
- Allowing verification to pass for reordered/duplicated/forked chains.
- Weakening fail-closed production checks.
- Expanding trust assumptions for offline verification.
- Changing frozen limits or failure classifications without explicit baseline update.

Executable baseline lock tests live in `tests/red_team/rt_security_baseline_freeze.py`.
