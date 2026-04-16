"""
CLI utilities for the Agentico License Server.

Usage:
    python manage.py generate-keys
    python manage.py create-tables
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def generate_keys():
    """Generate an ed25519 keypair for license signing."""
    import config
    from nacl.signing import SigningKey

    priv_path = config.LICENSE_PRIVATE_KEY_PATH
    pub_path = config.LICENSE_PUBLIC_KEY_PATH

    if os.path.exists(priv_path):
        print(f"ERROR: Private key already exists at {priv_path}")
        print("Delete it manually if you want to regenerate (this invalidates all existing licenses).")
        sys.exit(1)

    os.makedirs(os.path.dirname(priv_path), exist_ok=True)
    os.makedirs(os.path.dirname(pub_path), exist_ok=True)

    key = SigningKey.generate()

    with open(priv_path, "wb") as f:
        f.write(bytes(key))
    os.chmod(priv_path, 0o600)

    with open(pub_path, "wb") as f:
        f.write(bytes(key.verify_key))

    print(f"Private key: {priv_path} (chmod 600)")
    print(f"Public key:  {pub_path}")
    print("Copy the public key into the client app installer (sub-project #5).")


def create_tables():
    """Create all database tables."""
    from app import create_app
    from models import db

    app = create_app()
    with app.app_context():
        db.create_all()
        print("Tables created.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python manage.py <command>")
        print("Commands: generate-keys, create-tables")
        sys.exit(1)

    command = sys.argv[1]
    if command == "generate-keys":
        generate_keys()
    elif command == "create-tables":
        create_tables()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
