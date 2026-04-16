"""Tests for license_client.py — HW fingerprint, license verification."""
import base64
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest
from nacl.signing import SigningKey, VerifyKey


@pytest.fixture()
def keypair():
    sk = SigningKey.generate()
    return sk, sk.verify_key


@pytest.fixture()
def license_dir(tmp_path, keypair):
    sk, vk = keypair
    pub_path = tmp_path / "public.key"
    pub_path.write_bytes(bytes(vk))
    return tmp_path, sk, vk


def _sign_payload(sk, payload: dict) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signed = sk.sign(payload_bytes)
    return base64.b64encode(signed.signature + signed.message).decode()


def test_hw_fingerprint_is_deterministic():
    from license_client import get_hw_fingerprint
    fp1 = get_hw_fingerprint()
    fp2 = get_hw_fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 32
    assert all(c in "0123456789abcdef" for c in fp1)


def test_hw_fingerprint_is_hex_string():
    from license_client import get_hw_fingerprint
    fp = get_hw_fingerprint()
    int(fp, 16)


def test_read_license_valid(license_dir):
    from license_client import read_license
    tmp_path, sk, vk = license_dir
    payload = {
        "activation_key": "test123",
        "hw_fingerprint": "abc",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    blob = _sign_payload(sk, payload)
    dat_path = tmp_path / "license.dat"
    dat_path.write_text(blob)
    result = read_license(str(dat_path), str(tmp_path / "public.key"))
    assert result is not None
    assert result["activation_key"] == "test123"
    assert result["status"] == "active"


def test_read_license_missing_file(license_dir):
    from license_client import read_license
    tmp_path, sk, vk = license_dir
    result = read_license(str(tmp_path / "nonexistent.dat"), str(tmp_path / "public.key"))
    assert result is None


def test_read_license_tampered(license_dir):
    from license_client import read_license
    tmp_path, sk, vk = license_dir
    payload = {
        "activation_key": "test123",
        "hw_fingerprint": "abc",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    blob = _sign_payload(sk, payload)
    raw = base64.b64decode(blob)
    tampered = base64.b64encode(raw[:64] + b"TAMPERED" + raw[72:]).decode()
    dat_path = tmp_path / "license.dat"
    dat_path.write_text(tampered)
    result = read_license(str(dat_path), str(tmp_path / "public.key"))
    assert result is None


def test_verify_license_payload_valid():
    from license_client import verify_license_payload
    payload = {
        "hw_fingerprint": "abc123",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    assert verify_license_payload(payload, "abc123") == "valid"


def test_verify_license_payload_expired():
    from license_client import verify_license_payload
    payload = {
        "hw_fingerprint": "abc123",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    assert verify_license_payload(payload, "abc123") == "expired"


def test_verify_license_payload_hw_mismatch():
    from license_client import verify_license_payload
    payload = {
        "hw_fingerprint": "abc123",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    assert verify_license_payload(payload, "DIFFERENT") == "hw_mismatch"


def test_verify_license_payload_suspended():
    from license_client import verify_license_payload
    payload = {
        "hw_fingerprint": "abc123",
        "status": "suspended",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    assert verify_license_payload(payload, "abc123") == "suspended"


def test_verify_license_payload_revoked():
    from license_client import verify_license_payload
    payload = {
        "hw_fingerprint": "abc123",
        "status": "revoked",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    assert verify_license_payload(payload, "abc123") == "revoked"


def test_write_and_read_round_trip(license_dir):
    from license_client import write_license, read_license
    tmp_path, sk, vk = license_dir
    payload = {
        "activation_key": "roundtrip",
        "hw_fingerprint": "hw1",
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    blob = _sign_payload(sk, payload)
    dat_path = str(tmp_path / "license.dat")
    write_license(dat_path, blob)
    result = read_license(dat_path, str(tmp_path / "public.key"))
    assert result["activation_key"] == "roundtrip"
