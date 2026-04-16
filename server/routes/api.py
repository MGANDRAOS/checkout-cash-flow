"""
License API endpoints.
Public-facing, called by the client app on each customer's POS machine.
"""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from models import db, Customer, HeartbeatLog
from license import build_license_payload, sign_license, LICENSE_DURATION_DAYS
from app import limiter

api_bp = Blueprint("api", __name__)


def _json_error(message: str, status: int = 403):
    return jsonify({"error": message}), status


@api_bp.post("/api/license/activate")
@limiter.limit("10/minute")
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

    if customer.status == "active" and customer.hw_fingerprint != hw_fingerprint:
        return _json_error("invalid key")

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
@limiter.limit("10/minute")
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
@limiter.limit("10/minute")
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
