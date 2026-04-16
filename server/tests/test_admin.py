"""Tests for /admin/* pages."""
import pytest
from models import db, Customer


def _login(client):
    return client.post("/admin/login", data={
        "username": "testadmin",
        "password": "testpass",
    }, follow_redirects=True)


def test_login_page_renders(client):
    resp = client.get("/admin/login")
    assert resp.status_code == 200
    assert b"Login" in resp.data


def test_login_success(client):
    resp = _login(client)
    assert resp.status_code == 200


def test_login_bad_password(client):
    resp = client.post("/admin/login", data={
        "username": "testadmin",
        "password": "wrong",
    })
    assert resp.status_code == 200
    assert b"Invalid" in resp.data


def test_customers_requires_login(client):
    resp = client.get("/admin/customers")
    assert resp.status_code == 302


def test_customers_list_empty(client):
    _login(client)
    resp = client.get("/admin/customers")
    assert resp.status_code == 200
    assert b"Customers" in resp.data


def test_create_customer(client, db_session):
    _login(client)
    resp = client.post("/admin/customers/new", data={
        "name": "Test Shop",
        "email": "shop@test.com",
        "phone": "123456",
        "purchase_date": "2026-04-16",
        "amount_paid": "1200.00",
        "payment_notes": "Cash",
    }, follow_redirects=True)
    assert resp.status_code == 200
    customer = Customer.query.filter_by(name="Test Shop").first()
    assert customer is not None
    assert customer.status == "pending"
    assert len(customer.activation_key) == 64


def test_create_customer_name_required(client):
    _login(client)
    resp = client.post("/admin/customers/new", data={
        "name": "",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Customer.query.count() == 0


def _create_customer_in_db(db_session, name="Test Shop", status="pending"):
    import secrets
    c = Customer(
        name=name,
        activation_key=secrets.token_hex(32),
        status=status,
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_customer_detail_page(client, db_session):
    c = _create_customer_in_db(db_session)
    _login(client)
    resp = client.get(f"/admin/customers/{c.id}")
    assert resp.status_code == 200
    assert b"Test Shop" in resp.data


def test_suspend_active_customer(client, db_session):
    c = _create_customer_in_db(db_session, status="active")
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/suspend", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "suspended"


def test_revoke_customer(client, db_session):
    c = _create_customer_in_db(db_session, status="active")
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/revoke", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "revoked"


def test_reactivate_suspended_customer(client, db_session):
    c = _create_customer_in_db(db_session, status="suspended")
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/reactivate", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "active"


def test_deactivate_customer_clears_hw(client, db_session):
    c = _create_customer_in_db(db_session, status="active")
    c.hw_fingerprint = "HW-001"
    db_session.commit()
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/deactivate", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.status == "pending"
    assert c.hw_fingerprint is None


def test_extend_maintenance(client, db_session):
    from datetime import date, timedelta
    c = _create_customer_in_db(db_session)
    c.maintenance_renewal = date(2026, 4, 16)
    db_session.commit()
    _login(client)
    resp = client.post(f"/admin/customers/{c.id}/extend", follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(c)
    assert c.maintenance_renewal == date(2027, 4, 16)
