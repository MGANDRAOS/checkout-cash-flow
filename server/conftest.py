"""Pytest fixtures for the license server test suite."""
import os
import tempfile

import pytest
from nacl.signing import SigningKey

# Seed required env vars BEFORE any app import
_TEST_ENV = {
    "DATABASE_URL": "sqlite:///:memory:",
    "ADMIN_USERNAME": "testadmin",
    "ADMIN_PASSWORD": "testpass",
    "SECRET_KEY": "test-secret",
}

# Generate a temporary keypair for tests
_signing_key = SigningKey.generate()
_tmpdir = tempfile.mkdtemp()
_priv_path = os.path.join(_tmpdir, "test.key")
_pub_path = os.path.join(_tmpdir, "test.pub")

with open(_priv_path, "wb") as f:
    f.write(bytes(_signing_key))
with open(_pub_path, "wb") as f:
    f.write(bytes(_signing_key.verify_key))

_TEST_ENV["LICENSE_PRIVATE_KEY_PATH"] = _priv_path
_TEST_ENV["LICENSE_PUBLIC_KEY_PATH"] = _pub_path

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)


@pytest.fixture()
def app():
    from app import create_app
    from models import db

    application = create_app()
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with application.app_context():
        db.create_all()
        yield application
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    from models import db
    with app.app_context():
        yield db.session
