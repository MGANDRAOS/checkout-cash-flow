# License Server + Admin Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask + Postgres license server on `agentico.me` that issues ed25519-signed license files, handles heartbeats, and provides an admin dashboard for customer lifecycle management.

**Architecture:** Single Flask app in `server/` with two surfaces: a public License API (`/api/license/*`) and a private Admin dashboard (`/admin/*`). Postgres stores customers and heartbeat logs. Ed25519 keypair signs/verifies license payloads. Rate limiting on public endpoints.

**Tech Stack:** Python 3.11+, Flask, Flask-SQLAlchemy, Flask-Limiter, psycopg2-binary, PyNaCl (ed25519), pytest, gunicorn.

**Spec:** [docs/superpowers/specs/2026-04-16-license-server-design.md](../specs/2026-04-16-license-server-design.md)

---

## File Structure

```
server/
  app.py              -- Flask app factory, config loading, extensions init
  config.py           -- env validation (fail-fast, same pattern as reporting app)
  models.py           -- Customer, HeartbeatLog SQLAlchemy models
  license.py          -- ed25519 signing/verification, license payload generation
  routes/
    __init__.py       -- empty
    api.py            -- /api/license/* endpoints (activate, heartbeat, deactivate)
    admin.py          -- /admin/* pages + @admin_required decorator
  templates/admin/
    base.html         -- admin layout (Bootstrap 5 CDN)
    login.html
    customers.html
    customer_new.html
    customer_detail.html
    renewals.html
  manage.py           -- CLI: generate-keys
  requirements.txt
  .env.template
  conftest.py         -- pytest fixtures (test DB, test client, test keypair)
  tests/
    __init__.py       -- empty
    test_license.py   -- sign/verify unit tests
    test_api.py       -- API endpoint tests
    test_admin.py     -- admin dashboard tests
```

---

### Task 1: Scaffold `server/` with config + requirements

Create the directory structure, `requirements.txt`, `.env.template`, and `config.py` with fail-fast validation.

**Files:**
- Create: `server/requirements.txt`
- Create: `server/.env.template`
- Create: `server/config.py`
- Create: `server/routes/__init__.py`
- Create: `server/tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p server/routes server/tests server/templates/admin server/static
touch server/routes/__init__.py server/tests/__init__.py
```

- [ ] **Step 2: Create `server/requirements.txt`**

```
flask==3.0.3
flask-sqlalchemy==3.1.1
flask-limiter==3.8.0
psycopg2-binary==2.9.9
pynacl==1.5.0
python-dotenv==1.0.1
gunicorn==22.0.0
pytest==8.3.3
```

- [ ] **Step 3: Create `server/.env.template`**

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

- [ ] **Step 4: Create `server/config.py`**

```python
"""
Centralized configuration for the license server.
Validates required env vars at import time.
"""
import os
import sys
from typing import List

_REQUIRED_KEYS: List[str] = [
    "DATABASE_URL",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "LICENSE_PRIVATE_KEY_PATH",
    "LICENSE_PUBLIC_KEY_PATH",
    "SECRET_KEY",
]


def _validate_required() -> None:
    missing = [k for k in _REQUIRED_KEYS if not os.getenv(k, "").strip()]
    if missing:
        lines = ["FATAL: Required configuration missing:"]
        lines.extend(f"  - {k}" for k in missing)
        lines.append("")
        lines.append("Copy .env.template to .env and fill in all values, then restart.")
        raise RuntimeError("\n".join(lines))


_validate_required()

DATABASE_URL: str = os.environ["DATABASE_URL"]
ADMIN_USERNAME: str = os.environ["ADMIN_USERNAME"]
ADMIN_PASSWORD: str = os.environ["ADMIN_PASSWORD"]
LICENSE_PRIVATE_KEY_PATH: str = os.environ["LICENSE_PRIVATE_KEY_PATH"]
LICENSE_PUBLIC_KEY_PATH: str = os.environ["LICENSE_PUBLIC_KEY_PATH"]
SECRET_KEY: str = os.environ["SECRET_KEY"]
```

- [ ] **Step 5: Commit**

```bash
cd server
git add -A .
git commit -m "scaffold: server dir with config, requirements, .env.template"
```

---

### Task 2: Models — Customer and HeartbeatLog

**Files:**
- Create: `server/models.py`
- Create: `server/conftest.py`

- [ ] **Step 1: Create `server/models.py`**

```python
"""SQLAlchemy models for the license server."""
from datetime import datetime, timezone
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    activation_key = db.Column(db.String(64), unique=True, nullable=False)
    hw_fingerprint = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="pending")
    license_expiry = db.Column(db.DateTime(timezone=True))
    last_heartbeat = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Billing
    purchase_date = db.Column(db.Date)
    maintenance_renewal = db.Column(db.Date)
    amount_paid = db.Column(db.Numeric(10, 2))
    payment_notes = db.Column(db.Text)

    heartbeats = db.relationship("HeartbeatLog", backref="customer", lazy="dynamic")

    VALID_STATUSES = ("pending", "active", "suspended", "revoked")

    def __repr__(self):
        return f"<Customer {self.name} [{self.status}]>"


class HeartbeatLog(db.Model):
    __tablename__ = "heartbeat_log"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    hw_fingerprint = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    app_version = db.Column(db.String(20))

    def __repr__(self):
        return f"<HeartbeatLog customer={self.customer_id} at={self.timestamp}>"
```

- [ ] **Step 2: Create `server/conftest.py`**

This sets up a test Flask app with in-memory SQLite (fast tests, no Postgres needed) and a temporary ed25519 keypair.

```python
"""Pytest fixtures for the license server test suite."""
import os
import tempfile

import pytest
from nacl.signing import SigningKey

# Seed required env vars BEFORE any app import
_TEST_ENV = {
    "DATABASE_URL": "sqlite:///:memory:",
    "ADMIN_USERNAME": "testadmin",
    "ADMIN_PASSWORD": "testpass",
    "SECRET_KEY": "test-secret",
}

# Generate a temporary keypair for tests
_signing_key = SigningKey.generate()
_tmpdir = tempfile.mkdtemp()
_priv_path = os.path.join(_tmpdir, "test.key")
_pub_path = os.path.join(_tmpdir, "test.pub")

with open(_priv_path, "wb") as f:
    f.write(bytes(_signing_key))
with open(_pub_path, "wb") as f:
    f.write(bytes(_signing_key.verify_key))

_TEST_ENV["LICENSE_PRIVATE_KEY_PATH"] = _priv_path
_TEST_ENV["LICENSE_PUBLIC_KEY_PATH"] = _pub_path

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)


@pytest.fixture()
def app():
    from app import create_app
    from models import db

    application = create_app()
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with application.app_context():
        db.create_all()
        yield application
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    from models import db
    with app.app_context():
        yield db.session
```

- [ ] **Step 3: Commit**

```bash
git add models.py conftest.py
git commit -m "feat: Customer and HeartbeatLog models + test fixtures"
```

---

### Task 3: Ed25519 license signing module (TDD)

**Files:**
- Create: `server/tests/test_license.py`
- Create: `server/license.py`

- [ ] **Step 1: Write the failing tests**

Write to `server/tests/test_license.py`:

```python
"""Tests for ed25519 license signing and verification."""
import json
import time
from datetime import datetime, timezone, timedelta

import pytest


def test_sign_and_verify_round_trip():
    from license import sign_license, verify_license

    payload = {
        "activation_key": "abc123",
        "hw_fingerprint": "HW-TEST-001",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    signed = sign_license(payload)
    assert isinstance(signed, str)  # base64 string

    verified = verify_license(signed)
    assert verified["activation_key"] == "abc123"
    assert verified["hw_fingerprint"] == "HW-TEST-001"
    assert verified["status"] == "active"


def test_tampered_license_rejected():
    from license import sign_license, verify_license
    import base64

    payload = {
        "activation_key": "abc123",
        "hw_fingerprint": "HW-TEST-001",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    signed = sign_license(payload)

    # Tamper with the payload
    raw = base64.b64decode(signed)
    signature = raw[:64]
    payload_bytes = raw[64:]
    tampered = json.loads(payload_bytes)
    tampered["status"] = "revoked"
    tampered_bytes = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
    tampered_blob = base64.b64encode(signature + tampered_bytes).decode()

    with pytest.raises(Exception):
        verify_license(tampered_blob)


def test_build_license_payload():
    from license import build_license_payload

    payload = build_license_payload(
        activation_key="key123",
        hw_fingerprint="HW-001",
        status="active",
    )
    assert payload["activation_key"] == "key123"
    assert payload["hw_fingerprint"] == "HW-001"
    assert payload["status"] == "active"
    assert "expires_at" in payload
    assert "issued_at" in payload

    # expires_at should be ~7 days from now
    exp = datetime.fromisoformat(payload["expires_at"])
    now = datetime.now(timezone.utc)
    assert (exp - now).days >= 6
    assert (exp - now).days <= 7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server
python -m pytest tests/test_license.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'license'`.

- [ ] **Step 3: Create `server/license.py`**

```python
"""
Ed25519 license signing and verification.

Signs a JSON license payload with the server's private key.
The client app ships with the public key and verifies offline.

Wire format: base64(signature_64_bytes + json_payload_bytes)
"""
import base64
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError

import config

LICENSE_DURATION_DAYS = 7

# Load keys once at module level
_signing_key: SigningKey = None
_verify_key: VerifyKey = None


def _load_keys() -> None:
    global _signing_key, _verify_key
    if _signing_key is None:
        with open(config.LICENSE_PRIVATE_KEY_PATH, "rb") as f:
            _signing_key = SigningKey(f.read())
        with open(config.LICENSE_PUBLIC_KEY_PATH, "rb") as f:
            _verify_key = VerifyKey(f.read())


def build_license_payload(
    activation_key: str,
    hw_fingerprint: str,
    status: str,
) -> Dict[str, Any]:
    """Build the JSON-serializable license payload."""
    now = datetime.now(timezone.utc)
    return {
        "activation_key": activation_key,
        "hw_fingerprint": hw_fingerprint,
        "status": status,
        "expires_at": (now + timedelta(days=LICENSE_DURATION_DAYS)).isoformat(),
        "issued_at": now.isoformat(),
    }


def sign_license(payload: Dict[str, Any]) -> str:
    """
    Sign a license payload and return a base64-encoded blob.

    Format: base64(signature_64_bytes + json_payload_bytes)
    """
    _load_keys()
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signed = _signing_key.sign(payload_bytes)
    # signed.signature = 64 bytes, signed.message = payload_bytes
    return base64.b64encode(signed.signature + signed.message).decode()


def verify_license(signed_blob: str) -> Dict[str, Any]:
    """
    Verify a signed license blob and return the payload dict.

    Raises nacl.exceptions.BadSignatureError if tampered.
    """
    _load_keys()
    raw = base64.b64decode(signed_blob)
    signature = raw[:64]
    payload_bytes = raw[64:]
    _verify_key.verify(payload_bytes, signature)
    return json.loads(payload_bytes)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_license.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add license.py tests/test_license.py
git commit -m "feat: ed25519 license signing and verification module"
```

---

### Task 4: Flask app factory

**Files:**
- Create: `server/app.py`

- [ ] **Step 1: Create `server/app.py`**

```python
"""
Flask application factory for the Agentico License Server.
"""
from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402 — must come after load_dotenv

from flask import Flask  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
from models import db  # noqa: E402

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    limiter.init_app(app)

    from routes.api import api_bp
    from routes.admin import admin_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001)
```

- [ ] **Step 2: Run existing tests to verify no import breakage**

```bash
python -m pytest tests/test_license.py -v
```

Expected: 3 passed (app.py exists but the API/admin routes don't yet — that's fine, they'll be created in Tasks 5 and 7).

Note: This step will fail because `routes/api.py` and `routes/admin.py` don't exist yet. Create empty stubs first:

```python
# server/routes/api.py
from flask import Blueprint
api_bp = Blueprint("api", __name__)
```

```python
# server/routes/admin.py
from flask import Blueprint
admin_bp = Blueprint("admin", __name__)
```

- [ ] **Step 3: Commit**

```bash
git add app.py routes/api.py routes/admin.py
git commit -m "feat: Flask app factory with limiter and blueprint stubs"
```

---

### Task 5: License API endpoints (TDD)

**Files:**
- Create: `server/tests/test_api.py`
- Modify: `server/routes/api.py`

- [ ] **Step 1: Write the failing tests**

Write to `server/tests/test_api.py`:

```python
"""Tests for /api/license/* endpoints."""
import json
import secrets

import pytest
from models import db, Customer


def _create_customer(db_session, status="pending", hw_fingerprint=None):
    key = secrets.token_hex(32)
    c = Customer(
        name="Test Shop",
        activation_key=key,
        status=status,
        hw_fingerprint=hw_fingerprint,
    )
    db_session.add(c)
    db_session.commit()
    return c


# ── Activate ──────────────────────────────────────────────


def test_activate_pending_customer(client, db_session):
    c = _create_customer(db_session)
    resp = client.post("/api/license/activate", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "license_file" in data
    assert "expires_at" in data

    db_session.refresh(c)
    assert c.status == "active"
    assert c.hw_fingerprint == "HW-001"


def test_activate_invalid_key(client):
    resp = client.post("/api/license/activate", json={
        "activation_key": "nonexistent",
        "hw_fingerprint": "HW-001",
    })
    assert resp.status_code == 403
    assert "error" in resp.get_json()


def test_activate_revoked_customer(client, db_session):
    c = _create_customer(db_session, status="revoked")
    resp = client.post("/api/license/activate", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
    })
    assert resp.status_code == 403


def test_activate_hw_mismatch(client, db_session):
    c = _create_customer(db_session, status="active", hw_fingerprint="HW-001")
    resp = client.post("/api/license/activate", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-DIFFERENT",
    })
    assert resp.status_code == 403


def test_activate_reactivation_same_hw(client, db_session):
    c = _create_customer(db_session, status="active", hw_fingerprint="HW-001")
    resp = client.post("/api/license/activate", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
    })
    assert resp.status_code == 200
    assert "license_file" in resp.get_json()


# ── Heartbeat ─────────────────────────────────────────────


def test_heartbeat_active_customer(client, db_session):
    c = _create_customer(db_session, status="active", hw_fingerprint="HW-001")
    resp = client.post("/api/license/heartbeat", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
        "app_version": "1.0.0",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "license_file" in data
    assert "expires_at" in data
    assert data["update_available"] is False

    db_session.refresh(c)
    assert c.last_heartbeat is not None
    assert c.license_expiry is not None


def test_heartbeat_suspended_customer(client, db_session):
    c = _create_customer(db_session, status="suspended", hw_fingerprint="HW-001")
    resp = client.post("/api/license/heartbeat", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
        "app_version": "1.0.0",
    })
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "suspended"


def test_heartbeat_revoked_customer(client, db_session):
    c = _create_customer(db_session, status="revoked", hw_fingerprint="HW-001")
    resp = client.post("/api/license/heartbeat", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
        "app_version": "1.0.0",
    })
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "revoked"


def test_heartbeat_hw_mismatch(client, db_session):
    c = _create_customer(db_session, status="active", hw_fingerprint="HW-001")
    resp = client.post("/api/license/heartbeat", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-WRONG",
        "app_version": "1.0.0",
    })
    assert resp.status_code == 403


# ── Deactivate ────────────────────────────────────────────


def test_deactivate_active_customer(client, db_session):
    c = _create_customer(db_session, status="active", hw_fingerprint="HW-001")
    resp = client.post("/api/license/deactivate", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-001",
    })
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "deactivated"

    db_session.refresh(c)
    assert c.status == "pending"
    assert c.hw_fingerprint is None


def test_deactivate_wrong_hw(client, db_session):
    c = _create_customer(db_session, status="active", hw_fingerprint="HW-001")
    resp = client.post("/api/license/deactivate", json={
        "activation_key": c.activation_key,
        "hw_fingerprint": "HW-WRONG",
    })
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_api.py -v
```

Expected: all FAIL (routes not implemented).

- [ ] **Step 3: Implement `server/routes/api.py`**

```python
"""
License API endpoints.

Public-facing, called by the client app on each customer's POS machine.
Rate-limited to 10 req/min per IP.
"""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from models import db, Customer, HeartbeatLog
from license import build_license_payload, sign_license, LICENSE_DURATION_DAYS

api_bp = Blueprint("api", __name__)


def _json_error(message: str, status: int = 403):
    return jsonify({"error": message}), status


@api_bp.post("/api/license/activate")
def activate():
    data = request.get_json(silent=True) or {}
    activation_key = data.get("activation_key", "")
    hw_fingerprint = data.get("hw_fingerprint", "")

    if not activation_key or not hw_fingerprint:
        return _json_error("invalid key")

    customer = Customer.query.filter_by(activation_key=activation_key).first()
    if not customer:
        return _json_error("invalid key")

    if customer.status == "revoked":
        return _json_error("invalid key")

    if customer.status == "suspended":
        return _json_error("license suspended")

    # If already active, HW must match (re-activation on same machine)
    if customer.status == "active" and customer.hw_fingerprint != hw_fingerprint:
        return _json_error("invalid key")

    # Lock HW and activate
    customer.hw_fingerprint = hw_fingerprint
    customer.status = "active"
    customer.license_expiry = datetime.now(timezone.utc) + timedelta(days=LICENSE_DURATION_DAYS)
    db.session.commit()

    payload = build_license_payload(
        activation_key=customer.activation_key,
        hw_fingerprint=customer.hw_fingerprint,
        status="active",
    )
    signed = sign_license(payload)

    return jsonify({
        "license_file": signed,
        "expires_at": payload["expires_at"],
    })


@api_bp.post("/api/license/heartbeat")
def heartbeat():
    data = request.get_json(silent=True) or {}
    activation_key = data.get("activation_key", "")
    hw_fingerprint = data.get("hw_fingerprint", "")
    app_version = data.get("app_version", "")

    if not activation_key or not hw_fingerprint:
        return _json_error("invalid key")

    customer = Customer.query.filter_by(activation_key=activation_key).first()
    if not customer:
        return _json_error("invalid key")

    if customer.hw_fingerprint != hw_fingerprint:
        return _json_error("invalid key")

    if customer.status == "suspended":
        return jsonify({"status": "suspended"})

    if customer.status == "revoked":
        return jsonify({"status": "revoked"})

    if customer.status != "active":
        return _json_error("invalid key")

    # Roll expiry forward
    now = datetime.now(timezone.utc)
    customer.license_expiry = now + timedelta(days=LICENSE_DURATION_DAYS)
    customer.last_heartbeat = now
    db.session.add(HeartbeatLog(
        customer_id=customer.id,
        hw_fingerprint=hw_fingerprint,
        ip_address=request.remote_addr,
        app_version=app_version,
    ))
    db.session.commit()

    payload = build_license_payload(
        activation_key=customer.activation_key,
        hw_fingerprint=customer.hw_fingerprint,
        status="active",
    )
    signed = sign_license(payload)

    return jsonify({
        "status": "ok",
        "license_file": signed,
        "expires_at": payload["expires_at"],
        "update_available": False,
        "update_url": None,
    })


@api_bp.post("/api/license/deactivate")
def deactivate():
    data = request.get_json(silent=True) or {}
    activation_key = data.get("activation_key", "")
    hw_fingerprint = data.get("hw_fingerprint", "")

    if not activation_key or not hw_fingerprint:
        return _json_error("invalid key")

    customer = Customer.query.filter_by(activation_key=activation_key).first()
    if not customer or customer.hw_fingerprint != hw_fingerprint:
        return _json_error("invalid key")

    customer.hw_fingerprint = None
    customer.status = "pending"
    db.session.commit()

    return jsonify({"status": "deactivated"})
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_api.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add routes/api.py tests/test_api.py
git commit -m "feat: license API endpoints — activate, heartbeat, deactivate"
```

---

### Task 6: Rate limiting on API endpoints

Add the `10/minute` rate limit to all three license API endpoints.

**Files:**
- Modify: `server/routes/api.py`

- [ ] **Step 1: Add rate limiting decorators**

At the top of `server/routes/api.py`, add the import:

```python
from app import limiter
```

Then add this decorator to each of the three route functions (`activate`, `heartbeat`, `deactivate`), immediately after the `@api_bp.post(...)` decorator:

```python
@limiter.limit("10/minute")
```

So each endpoint looks like:

```python
@api_bp.post("/api/license/activate")
@limiter.limit("10/minute")
def activate():
    ...
```

Do the same for `heartbeat` and `deactivate`.

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_api.py tests/test_license.py -v
```

Expected: all 15 tests pass (rate limiter is disabled in test mode by default in flask-limiter).

- [ ] **Step 3: Commit**

```bash
git add routes/api.py
git commit -m "feat: rate-limit license API endpoints to 10/minute/IP"
```

---

### Task 7: Admin dashboard — login + customer list + create (TDD)

**Files:**
- Create: `server/tests/test_admin.py`
- Modify: `server/routes/admin.py`
- Create: `server/templates/admin/base.html`
- Create: `server/templates/admin/login.html`
- Create: `server/templates/admin/customers.html`
- Create: `server/templates/admin/customer_new.html`

- [ ] **Step 1: Write the failing tests**

Write to `server/tests/test_admin.py`:

```python
"""Tests for /admin/* pages."""
import pytest
from models import db, Customer


def _login(client):
    return client.post("/admin/login", data={
        "username": "testadmin",
        "password": "testpass",
    }, follow_redirects=True)


def test_login_page_renders(client):
    resp = client.get("/admin/login")
    assert resp.status_code == 200
    assert b"Login" in resp.data


def test_login_success(client):
    resp = _login(client)
    assert resp.status_code == 200


def test_login_bad_password(client):
    resp = client.post("/admin/login", data={
        "username": "testadmin",
        "password": "wrong",
    })
    assert resp.status_code == 200
    assert b"Invalid" in resp.data


def test_customers_requires_login(client):
    resp = client.get("/admin/customers")
    assert resp.status_code == 302  # redirect to login


def test_customers_list_empty(client):
    _login(client)
    resp = client.get("/admin/customers")
    assert resp.status_code == 200
    assert b"Customers" in resp.data


def test_create_customer(client, db_session):
    _login(client)
    resp = client.post("/admin/customers/new", data={
        "name": "Test Shop",
        "email": "shop@test.com",
        "phone": "123456",
        "purchase_date": "2026-04-16",
        "amount_paid": "1200.00",
        "payment_notes": "Cash",
    }, follow_redirects=True)
    assert resp.status_code == 200

    customer = Customer.query.filter_by(name="Test Shop").first()
    assert customer is not None
    assert customer.status == "pending"
    assert len(customer.activation_key) == 64  # 32 bytes hex


def test_create_customer_name_required(client):
    _login(client)
    resp = client.post("/admin/customers/new", data={
        "name": "",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Customer.query.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_admin.py -v
```

Expected: all FAIL (admin routes not implemented).

- [ ] **Step 3: Implement `server/routes/admin.py`**

```python
"""
Admin dashboard routes.

Protected by session-based login. Single admin account from .env.
"""
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

import config
from models import db, Customer

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin.customers"))
        flash("Invalid credentials.", "danger")
    return render_template("admin/login.html")


@admin_bp.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/admin/customers")
@admin_required
def customers():
    sort = request.args.get("sort", "created")
    q = request.args.get("q", "").strip()

    query = Customer.query
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%"))

    if sort == "renewal":
        query = query.order_by(Customer.maintenance_renewal.asc().nullslast())
    elif sort == "heartbeat":
        query = query.order_by(Customer.last_heartbeat.desc().nullslast())
    elif sort == "status":
        query = query.order_by(Customer.status.asc())
    else:
        query = query.order_by(Customer.created_at.desc())

    all_customers = query.all()
    return render_template("admin/customers.html", customers=all_customers, q=q)


@admin_bp.route("/admin/customers/new", methods=["GET", "POST"])
@admin_required
def customer_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "danger")
            return render_template("admin/customer_new.html")

        customer = Customer(
            name=name,
            email=request.form.get("email", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            activation_key=secrets.token_hex(32),
            status="pending",
            purchase_date=_parse_date(request.form.get("purchase_date")),
            amount_paid=_parse_decimal(request.form.get("amount_paid")),
            payment_notes=request.form.get("payment_notes", "").strip() or None,
        )
        db.session.add(customer)
        db.session.commit()
        flash(f"Customer '{name}' created. Activation key ready to copy.", "success")
        return redirect(url_for("admin.customer_detail", id=customer.id))

    return render_template("admin/customer_new.html")


def _parse_date(val):
    if not val or not val.strip():
        return None
    try:
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_decimal(val):
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None
```

- [ ] **Step 4: Create `server/templates/admin/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Agentico Admin{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
</head>
<body class="bg-light">
    {% if session.get('admin_logged_in') %}
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
        <div class="container">
            <a class="navbar-brand" href="/admin/customers">Agentico Admin</a>
            <div class="d-flex gap-3">
                <a href="/admin/customers" class="nav-link text-light">Customers</a>
                <a href="/admin/renewals" class="nav-link text-light">Renewals</a>
                <a href="/admin/logout" class="nav-link text-light">Logout</a>
            </div>
        </div>
    </nav>
    {% endif %}
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        {% for category, message in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
        {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: Create `server/templates/admin/login.html`**

```html
{% extends "admin/base.html" %}
{% block title %}Login — Agentico Admin{% endblock %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-4">
        <div class="card">
            <div class="card-body">
                <h4 class="card-title mb-4">Admin Login</h4>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Username</label>
                        <input type="text" name="username" class="form-control" required autofocus>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Login</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Create `server/templates/admin/customers.html`**

```html
{% extends "admin/base.html" %}
{% block title %}Customers — Agentico Admin{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3>Customers</h3>
    <a href="/admin/customers/new" class="btn btn-primary">
        <i class="bi bi-plus-lg me-1"></i>Create New Customer
    </a>
</div>

<form class="mb-3" method="GET">
    <div class="input-group" style="max-width:400px;">
        <input type="text" name="q" class="form-control" placeholder="Search by name..." value="{{ q }}">
        <button class="btn btn-outline-secondary" type="submit">Search</button>
    </div>
</form>

<div class="table-responsive">
    <table class="table table-hover">
        <thead>
            <tr>
                <th><a href="?sort=created" class="text-decoration-none">Name</a></th>
                <th><a href="?sort=status" class="text-decoration-none">Status</a></th>
                <th><a href="?sort=heartbeat" class="text-decoration-none">Last Heartbeat</a></th>
                <th><a href="?sort=renewal" class="text-decoration-none">Maintenance Due</a></th>
                <th>Key</th>
            </tr>
        </thead>
        <tbody>
            {% for c in customers %}
            <tr>
                <td><a href="/admin/customers/{{ c.id }}">{{ c.name }}</a></td>
                <td>
                    {% if c.status == 'active' %}
                    <span class="badge bg-success">Active</span>
                    {% elif c.status == 'pending' %}
                    <span class="badge bg-secondary">Pending</span>
                    {% elif c.status == 'suspended' %}
                    <span class="badge bg-warning text-dark">Suspended</span>
                    {% else %}
                    <span class="badge bg-danger">Revoked</span>
                    {% endif %}
                </td>
                <td>{{ c.last_heartbeat.strftime('%Y-%m-%d %H:%M') if c.last_heartbeat else '—' }}</td>
                <td>{{ c.maintenance_renewal.strftime('%Y-%m-%d') if c.maintenance_renewal else '—' }}</td>
                <td>
                    <code class="small">{{ c.activation_key[:8] }}...</code>
                    <button class="btn btn-sm btn-outline-secondary"
                            onclick="navigator.clipboard.writeText('{{ c.activation_key }}')">
                        <i class="bi bi-clipboard"></i>
                    </button>
                </td>
            </tr>
            {% else %}
            <tr><td colspan="5" class="text-muted">No customers yet.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 7: Create `server/templates/admin/customer_new.html`**

```html
{% extends "admin/base.html" %}
{% block title %}New Customer — Agentico Admin{% endblock %}
{% block content %}
<h3 class="mb-4">Create New Customer</h3>
<div class="card" style="max-width:600px;">
    <div class="card-body">
        <form method="POST">
            <div class="mb-3">
                <label class="form-label fw-semibold">Shop Name *</label>
                <input type="text" name="name" class="form-control" required>
            </div>
            <div class="mb-3">
                <label class="form-label">Email</label>
                <input type="email" name="email" class="form-control">
            </div>
            <div class="mb-3">
                <label class="form-label">Phone</label>
                <input type="text" name="phone" class="form-control">
            </div>
            <hr>
            <div class="mb-3">
                <label class="form-label">Purchase Date</label>
                <input type="date" name="purchase_date" class="form-control">
            </div>
            <div class="mb-3">
                <label class="form-label">Amount Paid ($)</label>
                <input type="number" step="0.01" name="amount_paid" class="form-control">
            </div>
            <div class="mb-3">
                <label class="form-label">Payment Notes</label>
                <textarea name="payment_notes" class="form-control" rows="2"></textarea>
            </div>
            <button type="submit" class="btn btn-primary">
                <i class="bi bi-plus-lg me-1"></i>Create Customer
            </button>
            <a href="/admin/customers" class="btn btn-outline-secondary ms-2">Cancel</a>
        </form>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_admin.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 9: Commit**

```bash
git add routes/admin.py templates/admin/ tests/test_admin.py
git commit -m "feat: admin dashboard — login, customer list, create customer"
```

---

### Task 8: Admin dashboard — customer detail + status actions

**Files:**
- Modify: `server/routes/admin.py`
- Create: `server/templates/admin/customer_detail.html`
- Add tests to: `server/tests/test_admin.py`

- [ ] **Step 1: Add tests to `server/tests/test_admin.py`**

Append to the existing test file:

```python
def _create_customer_in_db(db_session, name="Test Shop", status="pending"):
    import secrets
    c = Customer(
        name=name,
        activation_key=secrets.token_hex(32),
        status=status,
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_customer_detail_page(client, db_session):
    c = _create_customer_in_db(db_session)
    _login(client)
    resp = client.get(f"/admin/customers/{c.id}")
    assert resp.status_code == 200
    assert b"Test Shop" in resp.data


def test_suspend_active_customer(client, db_session):
    c = _create_customer_in_db(db_session, status="active")
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/suspend", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "suspended"


def test_revoke_customer(client, db_session):
    c = _create_customer_in_db(db_session, status="active")
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/revoke", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "revoked"


def test_reactivate_suspended_customer(client, db_session):
    c = _create_customer_in_db(db_session, status="suspended")
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/reactivate", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "active"


def test_deactivate_customer_clears_hw(client, db_session):
    c = _create_customer_in_db(db_session, status="active")
    c.hw_fingerprint = "HW-001"
    db_session.commit()
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/deactivate", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "pending"
    assert c.hw_fingerprint is None


def test_extend_maintenance(client, db_session):
    from datetime import date, timedelta
    c = _create_customer_in_db(db_session)
    c.maintenance_renewal = date(2026, 4, 16)
    db_session.commit()
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/extend", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.maintenance_renewal == date(2027, 4, 16)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_admin.py -v
```

Expected: new tests FAIL (routes not implemented).

- [ ] **Step 3: Add routes to `server/routes/admin.py`**

Append these routes to the existing `admin.py`:

```python
from datetime import date, timedelta


@admin_bp.route("/admin/customers/<int:id>")
@admin_required
def customer_detail(id):
    customer = Customer.query.get_or_404(id)
    heartbeats = customer.heartbeats.order_by(
        db.text("timestamp DESC")
    ).limit(50).all()
    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        heartbeats=heartbeats,
    )


@admin_bp.post("/admin/customers/<int:id>/suspend")
@admin_required
def customer_suspend(id):
    customer = Customer.query.get_or_404(id)
    if customer.status == "active":
        customer.status = "suspended"
        db.session.commit()
        flash(f"'{customer.name}' suspended.", "warning")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/revoke")
@admin_required
def customer_revoke(id):
    customer = Customer.query.get_or_404(id)
    if customer.status in ("active", "suspended"):
        customer.status = "revoked"
        db.session.commit()
        flash(f"'{customer.name}' revoked.", "danger")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/reactivate")
@admin_required
def customer_reactivate(id):
    customer = Customer.query.get_or_404(id)
    if customer.status == "suspended":
        customer.status = "active"
        db.session.commit()
        flash(f"'{customer.name}' reactivated.", "success")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/deactivate")
@admin_required
def customer_deactivate(id):
    customer = Customer.query.get_or_404(id)
    customer.hw_fingerprint = None
    customer.status = "pending"
    db.session.commit()
    flash(f"'{customer.name}' deactivated. Key can be re-activated on a new machine.", "info")
    return redirect(url_for("admin.customer_detail", id=id))


@admin_bp.post("/admin/customers/<int:id>/extend")
@admin_required
def customer_extend(id):
    customer = Customer.query.get_or_404(id)
    if customer.maintenance_renewal:
        customer.maintenance_renewal = customer.maintenance_renewal + timedelta(days=365)
    else:
        customer.maintenance_renewal = date.today() + timedelta(days=365)
    db.session.commit()
    flash(f"Maintenance extended to {customer.maintenance_renewal}.", "success")
    return redirect(url_for("admin.customer_detail", id=id))
```

- [ ] **Step 4: Create `server/templates/admin/customer_detail.html`**

```html
{% extends "admin/base.html" %}
{% block title %}{{ customer.name }} — Agentico Admin{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3>{{ customer.name }}</h3>
    <a href="/admin/customers" class="btn btn-outline-secondary btn-sm">Back to list</a>
</div>

<div class="row">
    <!-- Info Card -->
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header fw-semibold">Customer Info</div>
            <div class="card-body">
                <p><strong>Status:</strong>
                    {% if customer.status == 'active' %}<span class="badge bg-success">Active</span>
                    {% elif customer.status == 'pending' %}<span class="badge bg-secondary">Pending</span>
                    {% elif customer.status == 'suspended' %}<span class="badge bg-warning text-dark">Suspended</span>
                    {% else %}<span class="badge bg-danger">Revoked</span>{% endif %}
                </p>
                <p><strong>Email:</strong> {{ customer.email or '—' }}</p>
                <p><strong>Phone:</strong> {{ customer.phone or '—' }}</p>
                <p><strong>HW Fingerprint:</strong> <code>{{ customer.hw_fingerprint or '—' }}</code></p>
                <p><strong>Last Heartbeat:</strong> {{ customer.last_heartbeat.strftime('%Y-%m-%d %H:%M UTC') if customer.last_heartbeat else '—' }}</p>
                <p><strong>License Expiry:</strong> {{ customer.license_expiry.strftime('%Y-%m-%d %H:%M UTC') if customer.license_expiry else '—' }}</p>
                <p><strong>Created:</strong> {{ customer.created_at.strftime('%Y-%m-%d') }}</p>
                <hr>
                <p><strong>Activation Key:</strong></p>
                <div class="input-group mb-3">
                    <input type="text" class="form-control font-monospace" value="{{ customer.activation_key }}" readonly id="keyField">
                    <button class="btn btn-outline-secondary" onclick="navigator.clipboard.writeText(document.getElementById('keyField').value)">
                        <i class="bi bi-clipboard"></i> Copy
                    </button>
                </div>
            </div>
        </div>

        <!-- Status Actions -->
        <div class="card mb-4">
            <div class="card-header fw-semibold">Actions</div>
            <div class="card-body d-flex flex-wrap gap-2">
                {% if customer.status == 'active' %}
                <form method="POST" action="/admin/customers/{{ customer.id }}/suspend">
                    <button class="btn btn-warning btn-sm">Suspend</button>
                </form>
                <form method="POST" action="/admin/customers/{{ customer.id }}/revoke"
                      onsubmit="return confirm('Permanently revoke this license?')">
                    <button class="btn btn-danger btn-sm">Revoke</button>
                </form>
                <form method="POST" action="/admin/customers/{{ customer.id }}/deactivate">
                    <button class="btn btn-info btn-sm">Deactivate (clear HW)</button>
                </form>
                {% elif customer.status == 'suspended' %}
                <form method="POST" action="/admin/customers/{{ customer.id }}/reactivate">
                    <button class="btn btn-success btn-sm">Reactivate</button>
                </form>
                <form method="POST" action="/admin/customers/{{ customer.id }}/revoke"
                      onsubmit="return confirm('Permanently revoke?')">
                    <button class="btn btn-danger btn-sm">Revoke</button>
                </form>
                {% elif customer.status == 'revoked' %}
                <span class="text-muted">License permanently revoked.</span>
                {% else %}
                <span class="text-muted">Waiting for activation.</span>
                {% endif %}
            </div>
        </div>
    </div>

    <!-- Billing Card -->
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header fw-semibold">Billing</div>
            <div class="card-body">
                <p><strong>Purchase Date:</strong> {{ customer.purchase_date.strftime('%Y-%m-%d') if customer.purchase_date else '—' }}</p>
                <p><strong>Amount Paid:</strong> {{ '$%.2f'|format(customer.amount_paid) if customer.amount_paid else '—' }}</p>
                <p><strong>Maintenance Due:</strong>
                    {% if customer.maintenance_renewal %}
                        {{ customer.maintenance_renewal.strftime('%Y-%m-%d') }}
                        {% if customer.maintenance_renewal < today %}
                        <span class="badge bg-danger">Overdue</span>
                        {% endif %}
                    {% else %}
                        —
                    {% endif %}
                </p>
                <p><strong>Notes:</strong> {{ customer.payment_notes or '—' }}</p>
                <hr>
                <form method="POST" action="/admin/customers/{{ customer.id }}/extend">
                    <button class="btn btn-outline-primary btn-sm">
                        <i class="bi bi-calendar-plus me-1"></i>Extend Maintenance 1 Year
                    </button>
                </form>
            </div>
        </div>

        <!-- Heartbeat History -->
        <div class="card">
            <div class="card-header fw-semibold">Heartbeat History (last 50)</div>
            <div class="card-body p-0">
                <table class="table table-sm mb-0">
                    <thead><tr><th>Time</th><th>IP</th><th>Version</th></tr></thead>
                    <tbody>
                        {% for hb in heartbeats %}
                        <tr>
                            <td>{{ hb.timestamp.strftime('%Y-%m-%d %H:%M') }}</td>
                            <td><code>{{ hb.ip_address or '—' }}</code></td>
                            <td>{{ hb.app_version or '—' }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="3" class="text-muted p-3">No heartbeats yet.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

Note: the template references `today` — add it to the route's `render_template` call. In `customer_detail` route, change to:

```python
    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        heartbeats=heartbeats,
        today=date.today(),
    )
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_admin.py -v
```

Expected: all 13 tests pass (7 original + 6 new).

- [ ] **Step 6: Commit**

```bash
git add routes/admin.py templates/admin/customer_detail.html tests/test_admin.py
git commit -m "feat: admin customer detail page with status actions + billing"
```

---

### Task 9: Admin dashboard — renewals page

**Files:**
- Modify: `server/routes/admin.py`
- Create: `server/templates/admin/renewals.html`

- [ ] **Step 1: Add renewals route to `server/routes/admin.py`**

```python
@admin_bp.route("/admin/renewals")
@admin_required
def renewals():
    customers = Customer.query.filter(
        Customer.status.in_(["active", "suspended", "pending"])
    ).order_by(Customer.maintenance_renewal.asc().nullslast()).all()

    today_date = date.today()
    thirty_days = today_date + timedelta(days=30)

    stats = {
        "total_active": Customer.query.filter_by(status="active").count(),
        "overdue": Customer.query.filter(
            Customer.maintenance_renewal < today_date,
            Customer.status.in_(["active", "suspended"]),
        ).count(),
        "due_this_month": Customer.query.filter(
            Customer.maintenance_renewal >= today_date,
            Customer.maintenance_renewal <= thirty_days,
            Customer.status.in_(["active", "suspended"]),
        ).count(),
    }

    return render_template(
        "admin/renewals.html",
        customers=customers,
        today=today_date,
        thirty_days=thirty_days,
        stats=stats,
    )
```

- [ ] **Step 2: Create `server/templates/admin/renewals.html`**

```html
{% extends "admin/base.html" %}
{% block title %}Renewals — Agentico Admin{% endblock %}
{% block content %}
<h3 class="mb-4">Maintenance Renewals</h3>

<div class="row mb-4">
    <div class="col-md-4">
        <div class="card text-center">
            <div class="card-body">
                <h5 class="card-title">{{ stats.total_active }}</h5>
                <p class="card-text text-muted">Active Customers</p>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card text-center border-danger">
            <div class="card-body">
                <h5 class="card-title text-danger">{{ stats.overdue }}</h5>
                <p class="card-text text-muted">Overdue</p>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card text-center border-warning">
            <div class="card-body">
                <h5 class="card-title text-warning">{{ stats.due_this_month }}</h5>
                <p class="card-text text-muted">Due within 30 days</p>
            </div>
        </div>
    </div>
</div>

<div class="table-responsive">
    <table class="table table-hover">
        <thead>
            <tr><th>Name</th><th>Status</th><th>Maintenance Due</th><th>Action</th></tr>
        </thead>
        <tbody>
            {% for c in customers %}
            <tr>
                <td><a href="/admin/customers/{{ c.id }}">{{ c.name }}</a></td>
                <td>
                    {% if c.status == 'active' %}<span class="badge bg-success">Active</span>
                    {% elif c.status == 'pending' %}<span class="badge bg-secondary">Pending</span>
                    {% elif c.status == 'suspended' %}<span class="badge bg-warning text-dark">Suspended</span>
                    {% else %}<span class="badge bg-danger">Revoked</span>{% endif %}
                </td>
                <td>
                    {% if c.maintenance_renewal %}
                        {{ c.maintenance_renewal.strftime('%Y-%m-%d') }}
                        {% if c.maintenance_renewal < today %}
                        <span class="badge bg-danger">Overdue</span>
                        {% elif c.maintenance_renewal <= thirty_days %}
                        <span class="badge bg-warning text-dark">Due soon</span>
                        {% else %}
                        <span class="badge bg-success">OK</span>
                        {% endif %}
                    {% else %}
                        <span class="text-muted">Not set</span>
                    {% endif %}
                </td>
                <td>
                    <form method="POST" action="/admin/customers/{{ c.id }}/extend" style="display:inline;">
                        <button class="btn btn-outline-primary btn-sm">Extend 1 Year</button>
                    </form>
                </td>
            </tr>
            {% else %}
            <tr><td colspan="4" class="text-muted">No customers.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 3: Run all tests**

```bash
python -m pytest -v
```

Expected: all tests pass (license + api + admin).

- [ ] **Step 4: Commit**

```bash
git add routes/admin.py templates/admin/renewals.html
git commit -m "feat: admin renewals dashboard with stats and quick-extend"
```

---

### Task 10: manage.py — keypair generation CLI

**Files:**
- Create: `server/manage.py`

- [ ] **Step 1: Create `server/manage.py`**

```python
"""
CLI utilities for the Agentico License Server.

Usage:
    python manage.py generate-keys
    python manage.py create-tables
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def generate_keys():
    """Generate an ed25519 keypair for license signing."""
    import config
    from nacl.signing import SigningKey

    priv_path = config.LICENSE_PRIVATE_KEY_PATH
    pub_path = config.LICENSE_PUBLIC_KEY_PATH

    if os.path.exists(priv_path):
        print(f"ERROR: Private key already exists at {priv_path}")
        print("Delete it manually if you want to regenerate (this invalidates all existing licenses).")
        sys.exit(1)

    # Ensure parent directories exist
    os.makedirs(os.path.dirname(priv_path), exist_ok=True)
    os.makedirs(os.path.dirname(pub_path), exist_ok=True)

    key = SigningKey.generate()

    with open(priv_path, "wb") as f:
        f.write(bytes(key))
    os.chmod(priv_path, 0o600)

    with open(pub_path, "wb") as f:
        f.write(bytes(key.verify_key))

    print(f"Private key: {priv_path} (chmod 600)")
    print(f"Public key:  {pub_path}")
    print("Copy the public key into the client app installer (sub-project #5).")


def create_tables():
    """Create all database tables."""
    from app import create_app
    from models import db

    app = create_app()
    with app.app_context():
        db.create_all()
        print("Tables created.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python manage.py <command>")
        print("Commands: generate-keys, create-tables")
        sys.exit(1)

    command = sys.argv[1]
    if command == "generate-keys":
        generate_keys()
    elif command == "create-tables":
        create_tables()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
```

- [ ] **Step 2: Commit**

```bash
git add manage.py
git commit -m "feat: manage.py CLI — generate-keys and create-tables"
```

---

### Task 11: Final verification

**Files:** (read-only verification)

- [ ] **Step 1: Run full test suite**

```bash
cd server
python -m pytest -v
```

Expected: all tests pass (3 license + 12 api + 13 admin = 28 tests).

- [ ] **Step 2: Verify project structure**

```bash
find . -name "*.py" -o -name "*.html" -o -name "*.txt" -o -name ".env.template" | sort
```

Expected output matches the file structure from the plan header.

- [ ] **Step 3: Verify no hardcoded secrets**

```bash
grep -rniE "password\s*=\s*[\"'][^\"']+[\"']|secret\s*=\s*[\"'][^\"']+[\"']" --include="*.py" .
```

Expected: no output.

- [ ] **Step 4: Manual smoke test (on VPS after deployment)**

1. `pip install -r requirements.txt`
2. Copy `.env.template` → `.env`, fill in values.
3. `python manage.py generate-keys` — creates keypair.
4. `python manage.py create-tables` — creates Postgres tables.
5. `python app.py` — starts dev server on port 5001.
6. Open `http://localhost:5001/admin/login` — login works.
7. Create a customer — activation key appears on detail page.
8. `curl -X POST http://localhost:5001/api/license/activate -H "Content-Type: application/json" -d '{"activation_key":"<key>","hw_fingerprint":"test"}'` — returns signed license.
9. `curl -X POST http://localhost:5001/api/license/heartbeat -H "Content-Type: application/json" -d '{"activation_key":"<key>","hw_fingerprint":"test","app_version":"1.0"}'` — returns `status: ok`.
10. Suspend in admin → heartbeat returns `status: suspended`.
11. Check `/admin/renewals` — customer appears with correct badge.

- [ ] **Step 5: Commit any cleanup**

If any check required a fix:

```bash
git add -A
git commit -m "fix: final license server cleanup"
```

---

## Acceptance criteria (from spec)

- [ ] `server/` directory exists with all files from the project structure.
- [ ] `python manage.py generate-keys` creates an ed25519 keypair at configured paths.
- [ ] `POST /api/license/activate` returns a valid signed license for a pending customer.
- [ ] `POST /api/license/heartbeat` rolls expiry forward and returns `status: ok`.
- [ ] `POST /api/license/heartbeat` returns `status: suspended` or `status: revoked` for those states.
- [ ] `POST /api/license/deactivate` clears HW fingerprint and resets to `pending`.
- [ ] Admin dashboard: login, customer CRUD, status transitions, renewal extension all work.
- [ ] Rate limiting active on API endpoints (10 req/min/IP).
- [ ] All unit tests pass.
- [ ] `.env.template` documents every key.
