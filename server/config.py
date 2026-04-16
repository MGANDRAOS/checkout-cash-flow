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
