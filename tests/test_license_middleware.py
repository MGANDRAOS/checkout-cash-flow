"""Tests for license middleware request routing."""
from unittest.mock import patch

import pytest


@pytest.fixture()
def app_client():
    """Create a minimal Flask app with license middleware for testing."""
    from flask import Flask
    from license_middleware import register_license_middleware

    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = "test"
    app.config["TESTING"] = True

    register_license_middleware(app)

    @app.route("/")
    def index():
        return "OK", 200

    @app.route("/activate", methods=["GET"])
    def activate():
        return "ACTIVATE", 200

    @app.route("/license-expired")
    def license_expired():
        return "EXPIRED", 200

    return app.test_client()


@patch("license_middleware.get_license_status", return_value="not_activated")
def test_not_activated_redirects_to_activate(mock_status, app_client):
    resp = app_client.get("/")
    assert resp.status_code == 302
    assert "/activate" in resp.headers["Location"]


@patch("license_middleware.get_license_status", return_value="not_activated")
def test_not_activated_allows_activate_page(mock_status, app_client):
    resp = app_client.get("/activate")
    assert resp.status_code == 200
    assert b"ACTIVATE" in resp.data


@patch("license_middleware.get_license_status", return_value="valid")
def test_valid_allows_through(mock_status, app_client):
    resp = app_client.get("/")
    assert resp.status_code == 200
    assert b"OK" in resp.data


@patch("license_middleware.get_license_status", return_value="valid")
def test_valid_redirects_away_from_activate(mock_status, app_client):
    resp = app_client.get("/activate")
    assert resp.status_code == 302


@patch("license_middleware.get_license_status", return_value="expired")
def test_expired_redirects_to_lockout(mock_status, app_client):
    resp = app_client.get("/")
    assert resp.status_code == 302
    assert "/license-expired" in resp.headers["Location"]


@patch("license_middleware.get_license_status", return_value="expired")
def test_expired_allows_lockout_page(mock_status, app_client):
    resp = app_client.get("/license-expired")
    assert resp.status_code == 200
    assert b"EXPIRED" in resp.data


@patch("license_middleware.get_license_status", return_value="suspended")
def test_suspended_redirects_to_lockout(mock_status, app_client):
    resp = app_client.get("/")
    assert resp.status_code == 302
    assert "/license-expired" in resp.headers["Location"]


@patch("license_middleware.get_license_status", return_value="revoked")
def test_revoked_redirects_to_lockout(mock_status, app_client):
    resp = app_client.get("/")
    assert resp.status_code == 302
    assert "/license-expired" in resp.headers["Location"]
