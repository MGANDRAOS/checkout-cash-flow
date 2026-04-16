"""
Flask application factory for the Agentico License Server.
"""
from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402

from flask import Flask  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
from models import db  # noqa: E402

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    limiter.init_app(app)

    from routes.api import api_bp
    from routes.admin import admin_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001)
