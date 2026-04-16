# Client-Side License Enforcement — Design Spec

**Date:** 2026-04-16
**Status:** Draft, pending user approval
**Sub-project:** #3 of 7 in the productization roadmap
**Owner:** Majd Andraos

## Context

Sub-project #1 (codebase hardening) and sub-project #2 (license server + admin dashboard) are complete and deployed. The license server at `agentico.me:5001` issues ed25519-signed license files, handles heartbeats, and provides an admin dashboard. This sub-project adds client-side enforcement to the reporting app so it validates its license on startup, heartbeats every 6 hours, and locks out if the license is expired, suspended, or revoked.

## Goals

- On first run, gate the entire app behind an `/activate` page where the customer pastes their activation key.
- On every startup and every 6 hours, heartbeat to the license server to refresh the license and check status.
- Verify the on-disk license file (ed25519 signature, hardware fingerprint, expiry) before serving any page.
- Lock the app to a single machine via hardware fingerprint (CPU + disk serial + MAC address).
- On invalid/expired/suspended/revoked license, redirect all requests to a `/license-expired` lockout page with support contact info.
- 7-day offline grace period (license expires 7 days after last successful heartbeat).

## Non-goals

- Auto-update client (sub-project #4).
- MSI installer / first-run wizard (sub-projects #5/#6).
- License server changes (sub-project #2 is complete).
- Multi-machine licensing or floating licenses.

## Architecture

Three new modules added to the reporting app root:

### `license_client.py` — Pure logic, no Flask dependency

- `get_hw_fingerprint() -> str` — SHA-256 of CPU identifier + MAC address + Windows disk serial number. Returns a deterministic 32-char hex string. Stable across reboots; changes if hardware is swapped.
- `read_license(path) -> dict | None` — reads the on-disk license blob, base64-decodes, verifies ed25519 signature with the bundled public key, returns the payload dict. Returns `None` if file missing or signature invalid.
- `write_license(path, blob)` — writes the base64 license blob to disk.
- `verify_license_payload(payload, hw_fingerprint) -> str` — checks `hw_fingerprint` matches, `expires_at` > now, `status` == `active`. Returns one of: `"valid"`, `"expired"`, `"hw_mismatch"`, `"suspended"`, `"revoked"`.
- `activate(server_url, activation_key, hw_fingerprint) -> (blob, payload) | error` — POST to `/api/license/activate`.
- `heartbeat(server_url, activation_key, hw_fingerprint, app_version) -> (blob, payload, status) | error` — POST to `/api/license/heartbeat`.

Testable in isolation with a test keypair.

### `license_heartbeat.py` — Background daemon thread

On app startup:
1. Read `license/license.dat` from disk.
2. Verify signature with `license/public.key`.
3. Check `expires_at` > now and `hw_fingerprint` matches.
4. If valid: heartbeat to server, save refreshed license, set status to `"valid"`.
5. If invalid/missing: set status to `"expired"` (or `"not_activated"` if no license file and no `ACTIVATION_KEY`).

Then loop: sleep 6 hours → repeat steps 1-5.

Exposes a thread-safe `get_license_status() -> str` function that the middleware reads. Possible values: `"valid"`, `"not_activated"`, `"expired"`, `"suspended"`, `"revoked"`.

### `license_middleware.py` — Flask `before_request` hook

On every request, reads `get_license_status()` and routes:

| License state | Request path | Action |
|---|---|---|
| `not_activated` | `/activate` | Allow |
| `not_activated` | anything else | Redirect → `/activate` |
| `valid` | `/activate` | Redirect → `/` |
| `valid` | `/license-expired` | Redirect → `/` |
| `valid` | anything else | Allow (fall through to login check) |
| `expired` / `suspended` / `revoked` | `/license-expired` | Allow |
| `expired` / `suspended` / `revoked` | anything else | Redirect → `/license-expired` |

Always allowed regardless of state: `/static/*`.

This replaces the current single-layer `require_login` with a two-layer gate: license check first, then login check.

## Data on disk

```
license/
  license.dat    — signed license blob (base64), written by activate/heartbeat
  public.key     — ed25519 public key, shipped with the app (copied from VPS)
```

The `license/` directory lives next to `main.py`. The public key is committed to the repo (it's not a secret). `license.dat` is gitignored (per-installation).

## Hardware fingerprint

```python
import hashlib, platform, uuid, subprocess

def get_hw_fingerprint() -> str:
    cpu = platform.processor()
    mac = hex(uuid.getnode())
    try:
        disk = subprocess.check_output(
            "wmic diskdrive get serialnumber",
            shell=True, text=True
        ).strip().split('\n')[-1].strip()
    except Exception:
        disk = "unknown"
    raw = f"{cpu}|{mac}|{disk}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

Returns a 32-char hex string. Deterministic across reboots. Changes if motherboard, NIC, or primary disk is replaced — requiring deactivation on the old machine and re-activation on the new one.

## Startup flow

```
App starts (main.py)
  → load_dotenv()
  → import config (validates env — LICENSE_SERVER_URL, SUPPORT_CONTACT required)
  → create Flask app, init SQLAlchemy
  → start license heartbeat daemon thread
      → reads license/license.dat
      → verifies signature + HW + expiry
      → if valid: heartbeat to server, refresh license
      → if missing + no ACTIVATION_KEY: status = "not_activated"
      → if expired/tampered: status = "expired"
      → sleeps 6h, repeats
  → register license middleware (before_request)
  → register login middleware (before_request, runs after license)
  → register blueprints
  → serve requests
```

On first run (no `license.dat`, no `ACTIVATION_KEY` in `.env`):
- Heartbeat thread sets status to `not_activated`
- Middleware redirects all requests to `/activate`
- Customer pastes key → app calls `/api/license/activate` → receives signed license → writes `license/license.dat` → appends `ACTIVATION_KEY=<key>` to `.env`
- Heartbeat thread picks up the new license on next cycle
- Middleware allows through to `/login`

## New pages

### `/activate` — Activation form (one-time)

- Heading: "Activate Your License"
- One text field: "Activation Key"
- Submit button: "Activate"
- On success: writes license file, appends key to `.env`, flash "License activated!", redirect to `/login`
- On error (invalid key, HW mismatch, network failure): flash the error message, stay on page
- Extends `base.html` for consistent Agentico styling

### `/license-expired` — Lockout page

- Heading: "License Expired"
- Message: "Your reporting dashboard license has expired or been suspended. Contact support to renew."
- Contact info: configurable via `SUPPORT_CONTACT` env var (phone/WhatsApp)
- No nav bar, no dashboard links, no data access
- Extends `base.html` but with minimal nav

## New `.env` keys

```
# --- License client ---
LICENSE_SERVER_URL=http://agentico.me:5001    # required
ACTIVATION_KEY=                                # blank initially, written by activation flow
SUPPORT_CONTACT=+961-XX-XXXXXX                 # required, shown on lockout page
```

`LICENSE_SERVER_URL` and `SUPPORT_CONTACT` are required at startup (fail-fast in `config.py`). `ACTIVATION_KEY` is optional — starts blank, populated automatically on activation.

## File changes summary

| File | Change |
|---|---|
| **New: `license_client.py`** | HW fingerprint, license read/write/verify, activate call, heartbeat call |
| **New: `license_heartbeat.py`** | Daemon thread: startup validation + 6h heartbeat loop |
| **New: `license_middleware.py`** | Flask `before_request` hook: license gate |
| **New: `license/public.key`** | Ed25519 public key (copied from VPS) |
| **New: `templates/activate.html`** | Activation key entry form |
| **New: `templates/license_expired.html`** | Lockout page with contact info |
| **Modify: `config.py`** | Add `LICENSE_SERVER_URL`, `SUPPORT_CONTACT` to required keys; `ACTIVATION_KEY` as optional |
| **Modify: `main.py`** | Start heartbeat thread; replace `require_login` with two-layer gate (license → login) |
| **Modify: `.env.template`** | Add the 3 new keys |
| **Modify: `.gitignore`** | Add `license/license.dat` |
| **New: `tests/test_license_client.py`** | Unit tests for fingerprint, sign/verify, payload validation |
| **New: `tests/test_license_middleware.py`** | Tests for request routing in each license state |

## Testing

### Unit tests

- `tests/test_license_client.py` — fingerprint generation (deterministic), license read/write/verify round-trip (test keypair), payload validation (valid, expired, HW mismatch, wrong status), activate/heartbeat HTTP calls (mocked responses).
- `tests/test_license_middleware.py` — middleware routing: not_activated → `/activate`; valid → pass through; expired → `/license-expired`; static always allowed.

### Manual smoke test

1. Remove `license/license.dat` and `ACTIVATION_KEY` from `.env`.
2. Start app → all pages redirect to `/activate`.
3. Paste a valid key from admin dashboard → "License activated!", redirect to `/login`.
4. Log in → dashboards work normally.
5. Suspend the customer in admin → within 6 hours (or restart), app redirects to `/license-expired`.
6. Reactivate in admin → on next heartbeat, app unlocks.
7. Disconnect internet → app continues working for up to 7 days.
8. Wait for license to expire (or manually set clock forward) → lockout.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Heartbeat thread crashes silently | Wrap thread body in try/except with logging; thread restarts on exception |
| Customer clock is wrong (set far in the future then corrected) → license appears expired | `expires_at` is an absolute timestamp from the server; if their clock was wrong when the license was issued, expiry is also wrong. Heartbeat on next cycle corrects it. |
| `wmic` deprecated on newer Windows | `wmic diskdrive get serialnumber` still works on Windows 10/11 and Server 2019+. If it fails, falls back to `"unknown"` — fingerprint still includes CPU + MAC. |
| Customer deletes `license.dat` | App reverts to `not_activated` state. They can re-paste the same key (server recognizes it as re-activation on the same HW). |
| Network error during heartbeat | Thread catches the exception, logs it, retries on next 6h cycle. License stays valid until `expires_at` (7-day grace). |

## Acceptance criteria

1. First run with no license file → all requests redirect to `/activate`.
2. Pasting a valid activation key → license file written, app redirects to `/login`.
3. Pasting an invalid/revoked key → error flash, stays on `/activate`.
4. On startup, license file is verified: signature, HW fingerprint, expiry.
5. Background heartbeat fires every 6 hours and refreshes the license file.
6. Suspended/revoked status from heartbeat → app locks to `/license-expired`.
7. Offline for <7 days → app continues working. Offline for >7 days → lockout.
8. `/license-expired` page shows configurable support contact info.
9. Static assets (`/static/*`) always accessible (lockout page needs CSS).
10. All unit tests pass.
