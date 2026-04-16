"""
Client-side license operations.

Pure logic — no Flask dependency. Handles:
- Hardware fingerprint generation (CPU + MAC + disk serial)
- License file read/write/verify (ed25519 signature)
- License payload validation (HW match, expiry, status)
- HTTP calls to the license server (activate, heartbeat)
"""
import base64
import hashlib
import json
import logging
import os
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import urllib.request
import urllib.error

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

logger = logging.getLogger(__name__)


def get_hw_fingerprint() -> str:
    """
    Generate a deterministic hardware fingerprint.
    SHA-256 of CPU + MAC + disk serial, truncated to 32 hex chars.
    """
    cpu = platform.processor()
    mac = hex(uuid.getnode())
    try:
        disk = subprocess.check_output(
            "wmic diskdrive get serialnumber",
            shell=True, text=True
        ).strip().split("\n")[-1].strip()
    except Exception:
        disk = "unknown"
    raw = f"{cpu}|{mac}|{disk}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def read_license(license_path: str, pubkey_path: str) -> Optional[Dict[str, Any]]:
    """
    Read and verify a signed license file from disk.
    Returns the payload dict if valid, None if missing/invalid/tampered.
    """
    if not os.path.exists(license_path):
        return None
    try:
        with open(pubkey_path, "rb") as f:
            verify_key = VerifyKey(f.read())
        with open(license_path, "r") as f:
            blob = f.read().strip()
        raw = base64.b64decode(blob)
        signature = raw[:64]
        payload_bytes = raw[64:]
        verify_key.verify(payload_bytes, signature)
        return json.loads(payload_bytes)
    except (BadSignatureError, Exception) as e:
        logger.warning(f"License verification failed: {e}")
        return None


def write_license(license_path: str, blob: str) -> None:
    """Write a signed license blob to disk."""
    os.makedirs(os.path.dirname(license_path), exist_ok=True)
    with open(license_path, "w") as f:
        f.write(blob)


def verify_license_payload(payload: Dict[str, Any], hw_fingerprint: str) -> str:
    """
    Validate a license payload.
    Returns: "valid", "expired", "hw_mismatch", "suspended", "revoked"
    """
    if payload.get("hw_fingerprint") != hw_fingerprint:
        return "hw_mismatch"
    status = payload.get("status", "")
    if status == "suspended":
        return "suspended"
    if status == "revoked":
        return "revoked"
    if status != "active":
        return "expired"
    expires_at = payload.get("expires_at", "")
    try:
        expiry = datetime.fromisoformat(expires_at)
        if expiry < datetime.now(timezone.utc):
            return "expired"
    except (ValueError, TypeError):
        return "expired"
    return "valid"


def activate(server_url: str, activation_key: str, hw_fingerprint: str) -> Tuple[str, Dict]:
    """
    Call the license server's activate endpoint.
    Returns (license_blob, response_dict) on success.
    Raises RuntimeError on failure.
    """
    url = f"{server_url.rstrip('/')}/api/license/activate"
    data = json.dumps({
        "activation_key": activation_key,
        "hw_fingerprint": hw_fingerprint,
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            return body["license_file"], body
    except urllib.error.HTTPError as e:
        try:
            error_body = json.loads(e.read())
        except Exception:
            error_body = {}
        raise RuntimeError(error_body.get("error", f"Activation failed (HTTP {e.code})"))
    except Exception as e:
        raise RuntimeError(f"Cannot reach license server: {e}")


def heartbeat(
    server_url: str,
    activation_key: str,
    hw_fingerprint: str,
    app_version: str = "1.0.0",
) -> Tuple[str, Dict, str]:
    """
    Call the license server's heartbeat endpoint.
    Returns (license_blob, full_response, status_string) on success.
    Raises RuntimeError on network failure.
    """
    url = f"{server_url.rstrip('/')}/api/license/heartbeat"
    data = json.dumps({
        "activation_key": activation_key,
        "hw_fingerprint": hw_fingerprint,
        "app_version": app_version,
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            status = body.get("status", "ok")
            blob = body.get("license_file", "")
            return blob, body, status
    except urllib.error.HTTPError as e:
        try:
            error_body = json.loads(e.read())
        except Exception:
            error_body = {}
        raise RuntimeError(error_body.get("error", f"Heartbeat failed (HTTP {e.code})"))
    except Exception as e:
        raise RuntimeError(f"Cannot reach license server: {e}")
