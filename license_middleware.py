"""
License enforcement middleware.

Registers a Flask before_request hook that gates all requests based on
the current license status (read from the heartbeat thread).

Set LICENSE_ENFORCE=false in .env to bypass all checks (dev/maintenance mode).
"""
import os

from flask import Flask, request, redirect
from license_heartbeat import get_license_status

_ALWAYS_ALLOWED_PREFIXES = ("/static/",)


def _enforcement_enabled() -> bool:
    """Enforcement is ON unless explicitly disabled via env var."""
    return os.getenv("LICENSE_ENFORCE", "true").lower() not in ("false", "0", "no")


def register_license_middleware(app: Flask) -> None:
    """Register the license check as a before_request hook."""

    @app.before_request
    def check_license():
        # Bypass entirely if enforcement disabled
        if not _enforcement_enabled():
            return None

        path = request.path

        for prefix in _ALWAYS_ALLOWED_PREFIXES:
            if path.startswith(prefix):
                return None

        status = get_license_status()

        if status == "not_activated":
            if path == "/activate":
                return None
            return redirect("/activate")

        if status == "valid":
            if path == "/activate":
                return redirect("/")
            if path == "/license-expired":
                return redirect("/")
            return None

        # expired, suspended, revoked
        if path == "/license-expired":
            return None
        return redirect("/license-expired")
