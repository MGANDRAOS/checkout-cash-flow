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
    assert isinstance(signed, str)

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

    exp = datetime.fromisoformat(payload["expires_at"])
    now = datetime.now(timezone.utc)
    assert (exp - now).days >= 6
    assert (exp - now).days <= 7
