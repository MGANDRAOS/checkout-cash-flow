"""Flask test-app + client fixtures bound to an in-memory SQLite DB.

Lives under tests/ so it does NOT apply to the separate server/ suite.
The root conftest.py already populates dummy env vars for config import.
"""
import os

import pytest
from flask import Flask

from models import db as _db

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def app():
    app = Flask(__name__,
                template_folder=os.path.join(_REPO_ROOT, "templates"),
                static_folder=os.path.join(_REPO_ROOT, "static"))
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    _db.init_app(app)

    # Import here so model classes are registered on db.metadata before create_all.
    import models  # noqa: F401
    from routes.stock import stock_bp
    app.register_blueprint(stock_bp)

    with app.app_context():
        _db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()
