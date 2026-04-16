"""
Background license heartbeat daemon.

On app startup: validates the on-disk license. Then loops every 6 hours
to heartbeat the license server and refresh the license file.

Exposes get_license_status() for the middleware to read.
"""
import logging
import os
import threading
import time
from typing import Optional

import config
from license_client import (
    get_hw_fingerprint,
    read_license,
    write_license,
    verify_license_payload,
    heartbeat,
)

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 6 * 60 * 60  # 6 hours in seconds
LICENSE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license")
LICENSE_PATH = os.path.join(LICENSE_DIR, "license.dat")
PUBKEY_PATH = os.path.join(LICENSE_DIR, "public.key")

_status_lock = threading.Lock()
_license_status: str = "not_activated"  # valid | not_activated | expired | suspended | revoked


def get_license_status() -> str:
    """Thread-safe read of current license status."""
    with _status_lock:
        return _license_status


def _set_status(status: str) -> None:
    global _license_status
    with _status_lock:
        _license_status = status


def _check_and_heartbeat() -> None:
    """Run one license check + heartbeat cycle."""
    activation_key = config.ACTIVATION_KEY
    hw_fingerprint = get_hw_fingerprint()

    # No activation key → not activated
    if not activation_key:
        payload = read_license(LICENSE_PATH, PUBKEY_PATH)
        if payload is None:
            _set_status("not_activated")
            return
        activation_key = payload.get("activation_key", "")
        if not activation_key:
            _set_status("not_activated")
            return

    # Read and verify on-disk license
    payload = read_license(LICENSE_PATH, PUBKEY_PATH)
    if payload is not None:
        status = verify_license_payload(payload, hw_fingerprint)
        if status != "valid":
            _set_status(status)
        else:
            _set_status("valid")

    # Attempt heartbeat
    try:
        blob, response, server_status = heartbeat(
            server_url=config.LICENSE_SERVER_URL,
            activation_key=activation_key,
            hw_fingerprint=hw_fingerprint,
        )
        if server_status == "ok" and blob:
            write_license(LICENSE_PATH, blob)
            _set_status("valid")
            logger.info("License heartbeat OK, refreshed.")
        elif server_status in ("suspended", "revoked"):
            _set_status(server_status)
            logger.warning(f"License server returned: {server_status}")
        else:
            logger.warning(f"Unexpected heartbeat status: {server_status}")
    except RuntimeError as e:
        logger.warning(f"Heartbeat failed (offline?): {e}")


def _heartbeat_loop() -> None:
    """Daemon loop: check immediately, then every 6 hours."""
    while True:
        try:
            _check_and_heartbeat()
        except Exception as e:
            logger.error(f"Heartbeat thread error: {e}", exc_info=True)
        time.sleep(HEARTBEAT_INTERVAL)


def start_heartbeat_thread() -> threading.Thread:
    """Start the background heartbeat daemon. Call once at app startup."""
    t = threading.Thread(target=_heartbeat_loop, daemon=True, name="license-heartbeat")
    t.start()
    logger.info("License heartbeat thread started.")
    return t


def notify_activated(activation_key: str, license_blob: str) -> None:
    """
    Called by the /activate route after successful activation.
    Writes the license, updates status immediately.
    """
    write_license(LICENSE_PATH, license_blob)
    _set_status("valid")
    logger.info("License activated and saved.")
