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
