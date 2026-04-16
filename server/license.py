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
