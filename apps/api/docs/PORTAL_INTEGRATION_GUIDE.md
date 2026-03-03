# Portal Integration Guide

This guide defines the production integration flow for tenant-facing portals and external customers.

## Response Contract

All successful API responses:

```json
{ "data": { } }
```

All API errors:

```json
{
  "error": {
    "code": "STABLE_CODE",
    "message": "Human readable message",
    "request_id": "uuid"
  }
}
```

## Stable Error Codes

- `AUTH_MISSING`
- `AUTH_INVALID`
- `AUTH_REVOKED`
- `TENANT_DISABLED`
- `RATE_LIMIT_EXCEEDED`
- `IDEMPOTENCY_CONFLICT`
- `NOT_FOUND`
- `VALIDATION_ERROR`

Use `error.code` for frontend logic. Do not parse `message`.

## Tenant Onboarding Flow

1. Platform admin creates tenant:
   - `POST /admin/tenants`
2. Platform admin creates tenant API key:
   - `POST /admin/tenants/{id}/api-keys`
3. Portal stores key securely (secret manager, never in client code).

## Consent Lifecycle (Upsert Model)

- Use `PUT /consents` to create/update by `(subject_id, purpose)`.
- Include `Idempotency-Key` for retries to avoid duplicate writes.

## Revoke Consent

- Use `POST /consents/{id}/revoke`.
- Optional `Idempotency-Key` supported.

## API Key Rotation

1. Create new key: `POST /admin/tenants/{id}/api-keys`
2. Update portal/backend to use new key.
3. Revoke old key: `POST /admin/api-keys/{id}/revoke`

## Webhook Subscription & Verification

1. Create endpoint: `POST /webhooks` (secret shown once only).
2. Store secret securely.
3. Verify each delivery:
   - Read `X-Webhook-Timestamp`
   - Compute `HMAC_SHA256(secret, timestamp + "." + body)`
   - Compare with `X-Webhook-Signature` using constant-time compare.

## Pagination Rules

List endpoints support:

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

## cURL Examples

### Upsert Consent

```bash
curl -X PUT "http://127.0.0.1:8000/consents" \
  -H "Authorization: Bearer clb2b_fake_example_key" \
  -H "Idempotency-Key: 11111111-1111-1111-1111-111111111111" \
  -H "Content-Type: application/json" \
  -d "{\"subject_id\":\"user_123\",\"purpose\":\"marketing_emails\",\"status\":\"ACTIVE\"}"
```

### Revoke Consent

```bash
curl -X POST "http://127.0.0.1:8000/consents/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/revoke" \
  -H "Authorization: Bearer clb2b_fake_example_key" \
  -H "Idempotency-Key: 22222222-2222-2222-2222-222222222222"
```

### Idempotent Retry (same key + same payload)

```bash
curl -X PUT "http://127.0.0.1:8000/consents" \
  -H "Authorization: Bearer clb2b_fake_example_key" \
  -H "Idempotency-Key: 33333333-3333-3333-3333-333333333333" \
  -H "Content-Type: application/json" \
  -d "{\"subject_id\":\"user_123\",\"purpose\":\"marketing_emails\",\"status\":\"ACTIVE\"}"
```

## PowerShell Examples

### Upsert Consent

```powershell
$headers = @{
  Authorization = "Bearer clb2b_fake_example_key"
  "Idempotency-Key" = "11111111-1111-1111-1111-111111111111"
  "Content-Type" = "application/json"
}
$body = @{
  subject_id = "user_123"
  purpose = "marketing_emails"
  status = "ACTIVE"
} | ConvertTo-Json

Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8000/consents" -Headers $headers -Body $body
```

### Revoke Consent

```powershell
$headers = @{
  Authorization = "Bearer clb2b_fake_example_key"
  "Idempotency-Key" = "22222222-2222-2222-2222-222222222222"
}

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/consents/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/revoke" -Headers $headers
```

## Webhook Verification Snippet (Python)

```python
import hmac
import hashlib

def verify_webhook(secret: str, timestamp: str, raw_body: bytes, signature_hex: str) -> bool:
    signed = f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_hex)
```
