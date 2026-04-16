# License Server + Admin Dashboard — Design Spec

**Date:** 2026-04-16
**Status:** Draft, pending user approval
**Sub-project:** #2 of 7 in the productization roadmap
**Owner:** Majd Andraos

## Context

The reporting dashboard (sub-project #1, complete) is now hardened for distribution: no hardcoded credentials, fail-fast config validation, finance modules removed. Sub-project #2 builds the server-side licensing infrastructure that lives on the VPS (`agentico.me`). It issues, refreshes, and revokes signed license files that the on-prem client app (sub-project #3) will validate on startup and every 6 hours.

## Goals

- A Flask + Postgres license server running on `agentico.me` with two surfaces: a public License API and a private Admin dashboard.
- Ed25519-signed license files that the client can verify offline for up to 7 days.
- Admin dashboard to manage the full customer lifecycle: create, activate, suspend, revoke, track billing and renewals.
- Heartbeat endpoint that rolls license expiry forward and will carry auto-update manifests (sub-project #4).
- Single admin account (creds in `.env`), manual activation-key distribution (copy-paste).

## Non-goals

- Client-side license enforcement (sub-project #3).
- Auto-update client and manifest serving (sub-project #4).
- MSI installer (sub-project #5).
- Multi-admin accounts, RBAC, or audit logging.
- Email delivery of activation keys.
- Payment gateway integration (Stripe, etc.).

## Architecture

One Flask application on the VPS with two surfaces:

1. **License API** (`/api/license/...`) — public, called by the client app on each customer's POS machine. Three endpoints: activate, heartbeat, deactivate. Stateless JSON. No auth beyond the activation key itself.
2. **Admin dashboard** (`/admin/...`) — private, protected by session-based login (same pattern as the reporting app). HTML pages to list customers, create/edit/suspend/revoke, view heartbeat history, see upcoming renewals.

**Postgres** stores the `customers` and `heartbeat_log` tables.

**Ed25519 keypair:** Private key on VPS (signs license files). Public key ships inside the client app (verifies signatures). Generated once during initial setup via a CLI command, stored at file paths configured in `.env`.

## Database schema

### `customers` table

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | |
| `name` | VARCHAR(255) | NOT NULL | Shop / owner name |
| `email` | VARCHAR(255) | | Optional contact |
| `phone` | VARCHAR(50) | | Optional contact |
| `activation_key` | VARCHAR(64) | UNIQUE NOT NULL | Random hex, generated on create |
| `hw_fingerprint` | VARCHAR(255) | | Set on first activation |
| `status` | VARCHAR(20) | DEFAULT 'pending' | pending / active / suspended / revoked |
| `license_expiry` | TIMESTAMP | | Rolls forward on each heartbeat |
| `last_heartbeat` | TIMESTAMP | | Last successful heartbeat |
| `created_at` | TIMESTAMP | DEFAULT NOW() | |
| `purchase_date` | DATE | | When the customer paid |
| `maintenance_renewal` | DATE | | When yearly maintenance is next due |
| `amount_paid` | DECIMAL(10,2) | | Total paid to date |
| `payment_notes` | TEXT | | Free-text billing notes |

### `heartbeat_log` table

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | |
| `customer_id` | INTEGER | REFERENCES customers(id) | |
| `timestamp` | TIMESTAMP | DEFAULT NOW() | |
| `hw_fingerprint` | VARCHAR(255) | | For audit |
| `ip_address` | VARCHAR(45) | | IPv4 or IPv6 |
| `app_version` | VARCHAR(20) | | Client app version |

### Status lifecycle

- `pending` — customer created in admin, activation key not yet used.
- `active` — key activated on a machine; HW fingerprint locked.
- `suspended` — admin paused the license (e.g., payment dispute). Resumes on un-suspend.
- `revoked` — permanent kill. Customer must contact admin for a new key.

Transitions:
- `pending` → `active` (on activation)
- `active` → `suspended` (admin action)
- `active` → `revoked` (admin action)
- `suspended` → `active` (admin un-suspend)
- `active` → `pending` (on deactivation — clears HW fingerprint, allows re-activation on a new machine)

## License API endpoints

### `POST /api/license/activate`

**Request:** `{ "activation_key": "...", "hw_fingerprint": "..." }`

**Logic:**
1. Look up customer by `activation_key`.
2. If not found or status is `revoked`: return `{ "error": "invalid key" }`, 403.
3. If status is `suspended`: return `{ "error": "license suspended" }`, 403.
4. If status is `active` and `hw_fingerprint` does not match: return `{ "error": "invalid key" }`, 403 (license already bound to a different machine).
5. If status is `active` and `hw_fingerprint` matches: treat as re-activation (refresh).
6. If status is `pending`: lock `hw_fingerprint`, set status to `active`.
7. Set `license_expiry` to now + 7 days.
8. Sign the license payload with ed25519 private key.
9. Return `{ "license_file": "<base64-encoded signed license>", "expires_at": "..." }`, 200.

### `POST /api/license/heartbeat`

**Request:** `{ "activation_key": "...", "hw_fingerprint": "...", "app_version": "..." }`

**Logic:**
1. Look up customer by `activation_key`.
2. If not found: return `{ "error": "invalid key" }`, 403.
3. If `hw_fingerprint` does not match: return `{ "error": "invalid key" }`, 403.
4. If status is `suspended`: return `{ "status": "suspended" }`, 200.
5. If status is `revoked`: return `{ "status": "revoked" }`, 200.
6. If status is `active`:
   - Roll `license_expiry` forward to now + 7 days.
   - Update `last_heartbeat` to now.
   - Insert row into `heartbeat_log`.
   - Sign fresh license payload.
   - Return `{ "status": "ok", "license_file": "<base64>", "expires_at": "...", "update_available": false, "update_url": null }`, 200.

The `update_available` and `update_url` fields are placeholders for sub-project #4. For now they always return `false` and `null`.

### `POST /api/license/deactivate`

**Request:** `{ "activation_key": "...", "hw_fingerprint": "..." }`

**Logic:**
1. Look up customer by `activation_key`.
2. If not found or `hw_fingerprint` does not match: return `{ "error": "invalid key" }`, 403.
3. Clear `hw_fingerprint`, set status to `pending`.
4. Return `{ "status": "deactivated" }`, 200.

**Use case:** Customer moves to a new POS machine. They (or admin) deactivate first, then re-activate on the new machine.

### Rate limiting

All three endpoints are rate-limited to 10 requests per minute per IP address to prevent brute-force key guessing. Use `flask-limiter` with in-memory backend (sufficient for single-server deployment).

### Error responses

All errors return `{ "error": "<message>" }` with appropriate HTTP status. Error messages are intentionally vague for public endpoints — never reveal whether a key exists vs. is revoked.

## Signed license file format

The license file is a JSON payload + an ed25519 signature, base64-encoded as a single blob.

### Payload

```json
{
  "activation_key": "abc123...",
  "hw_fingerprint": "CPU-xyz-DISK-abc-MAC-def",
  "status": "active",
  "expires_at": "2026-04-23T08:00:00Z",
  "issued_at": "2026-04-16T08:00:00Z"
}
```

### Encoding

1. JSON-serialize the payload (sorted keys, no whitespace).
2. Sign the serialized bytes with ed25519 private key → 64-byte signature.
3. Concatenate: `signature (64 bytes) + payload bytes`.
4. Base64-encode the concatenation.
5. Return as a single string in the API response.

### Client-side verification (sub-project #3, documented here for interface clarity)

1. Base64-decode.
2. Split: first 64 bytes = signature, rest = payload.
3. Verify signature with the public key.
4. Parse payload JSON.
5. Check: `hw_fingerprint` matches this machine, `expires_at` > now, `status` == `active`.
6. If any check fails: lock the app.

## Admin dashboard pages

Five pages, server-rendered with Flask templates (Bootstrap 5, same design language as the Agentico reporting app):

### 1. Login (`/admin/login`)

Username/password form. Credentials from `.env` (`ADMIN_USERNAME`, `ADMIN_PASSWORD`). Session-based auth with `@admin_required` decorator on all other admin routes.

### 2. Customer list (`/admin/customers`)

- Table: name, status (color-coded badge), last heartbeat (relative time), maintenance renewal date, activation key (masked, "Copy" button).
- "Create New Customer" button.
- Search by name.
- Sort by status, renewal date, last heartbeat.

### 3. Create customer (`/admin/customers/new`)

- Form fields: name (required), email, phone, purchase date, amount paid, payment notes.
- On submit: generate random 32-byte hex activation key, insert customer with status `pending`, redirect to detail page.

### 4. Customer detail (`/admin/customers/<id>`)

- All customer fields displayed; billing fields editable inline.
- "Copy Activation Key" button (full key shown here).
- Status action buttons: Suspend (if active), Revoke (if active/suspended), Reactivate (if suspended), Deactivate (if active — clears HW fingerprint).
- Heartbeat history: table of last 50 entries (timestamp, IP, app version).
- "Extend Maintenance 1 Year" button (adds 365 days to `maintenance_renewal`).

### 5. Renewals dashboard (`/admin/renewals`)

- All customers sorted by `maintenance_renewal` ascending.
- Color coding: red badge if overdue, yellow if due within 30 days, green otherwise.
- "Extend 1 Year" quick-action button per row.
- Summary stats at top: total active customers, overdue count, due-this-month count.

## Configuration (`.env.template`)

```
# --- Postgres ---
DATABASE_URL=postgresql://user:pass@localhost:5432/agentico

# --- Admin auth ---
ADMIN_USERNAME=
ADMIN_PASSWORD=

# --- Ed25519 signing ---
LICENSE_PRIVATE_KEY_PATH=/etc/agentico/license.key
LICENSE_PUBLIC_KEY_PATH=/etc/agentico/license.pub

# --- Flask ---
SECRET_KEY=
```

The ed25519 keypair is generated once via `python manage.py generate-keys` and stored at the configured paths. The private key never leaves the VPS. The public key is copied into the client app installer (sub-project #5).

## Project structure

Separate codebase from the reporting app. Lives in `server/` directory of the same repo for now.

```
server/
  app.py              -- Flask app factory, config loading, extensions
  config.py           -- env validation (same fail-fast pattern as reporting app)
  models.py           -- Customer, HeartbeatLog SQLAlchemy models
  license.py          -- ed25519 signing/verification, license payload generation
  routes/
    api.py            -- /api/license/* endpoints
    admin.py          -- /admin/* pages + auth decorator
  templates/admin/
    login.html
    customers.html
    customer_new.html
    customer_detail.html
    renewals.html
  static/             -- admin CSS/JS (minimal, Bootstrap CDN)
  manage.py           -- CLI: generate-keys
  requirements.txt    -- flask, flask-sqlalchemy, flask-limiter, psycopg2-binary, pynacl, gunicorn
  .env.template
```

~10 source files. Each file has one clear responsibility.

## Testing

### Unit tests

- `tests/test_license.py` — sign/verify round-trip, tamper detection, expired license rejection.
- `tests/test_api.py` — activate (happy path, invalid key, revoked, HW mismatch, re-activation), heartbeat (happy path, suspended, revoked, HW mismatch), deactivate (happy path, wrong HW). Uses Flask test client + in-memory SQLite for speed.
- `tests/test_admin.py` — create customer (generates key), suspend/revoke/reactivate status transitions, extend maintenance.

### Manual smoke test

After deployment to VPS:
1. Generate keypair via `manage.py`.
2. Create a customer in admin, copy key.
3. `curl -X POST https://agentico.me/api/license/activate -d '{"activation_key":"...","hw_fingerprint":"test"}'` → returns signed license.
4. `curl -X POST https://agentico.me/api/license/heartbeat -d '{"activation_key":"...","hw_fingerprint":"test","app_version":"1.0"}'` → returns `status: ok`.
5. Suspend in admin → heartbeat returns `status: suspended`.
6. Revoke → heartbeat returns `status: revoked`.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Ed25519 private key leaked | Store at restricted file path (`chmod 600`), never in repo or `.env` value. Rotate: generate new keypair, push new public key via auto-update, re-sign all active licenses. |
| Activation key brute-forced | 32-byte hex = 256-bit entropy (infeasible). Rate limiting (10/min/IP) adds defense. |
| Postgres down → heartbeats fail → customers lock out in 7 days | 7-day grace is generous; Postgres uptime on a single VPS is ~99.9%. Set up a simple health check (cron `pg_isready`) and alert yourself. |
| Admin dashboard exposed to internet | Session auth + strong password. Future: add IP allowlist or Cloudflare Access. |
| Customer disputes HW fingerprint change (new motherboard) | Deactivate endpoint clears fingerprint; admin can also clear it from the dashboard. |

## Acceptance criteria

Sub-project #2 is done when:

1. `server/` directory exists with all files from the project structure above.
2. `python manage.py generate-keys` creates an ed25519 keypair at configured paths.
3. `POST /api/license/activate` returns a valid signed license for a pending customer.
4. `POST /api/license/heartbeat` rolls expiry forward for an active customer and returns `status: ok`.
5. `POST /api/license/heartbeat` returns `status: suspended` or `status: revoked` for those states.
6. `POST /api/license/deactivate` clears HW fingerprint and resets status to `pending`.
7. Admin dashboard: login works, customer CRUD works, status transitions work, renewal extension works.
8. Rate limiting active on API endpoints (10 req/min/IP).
9. All unit tests pass.
10. `.env.template` documents every key.
