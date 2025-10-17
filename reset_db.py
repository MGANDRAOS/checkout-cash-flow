import os
from flask import Flask
from models import db, Envelope, EnvelopeTransaction, DailyClosing, FixedBill, AppSetting, FixedCollection

# --- Configuration ---
# 1. Initialize a minimal Flask app
app = Flask(__name__)

# 2. Configure the database URI
# IMPORTANT: Replace 'sqlite:///your_database.db' with your actual database connection string
# This is typically found in your main Flask app's config.
# Example for a local SQLite file:
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///checkout.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 3. Initialize the SQLAlchemy instance with the app
db.init_app(app)
# ---------------------

# List of models/tables to be DROPPED
# Exclude AppSetting and FixedBill
MODELS_TO_DROP = [
    Envelope,
    EnvelopeTransaction,
    DailyClosing,
    FixedCollection,
    # FixedBill is excluded
    # AppSetting is excluded
]

def reset_database_selective():
    """Drops and re-creates a specific list of tables, preserving others."""
    with app.app_context():
        print("--- Starting Selective Database Reset ---")
        
        # 1. Drop the selected tables
        print(f"Dropping tables: {[model.__tablename__ for model in MODELS_TO_DROP]}...")
        
        # We use db.metadata.drop_all() with a list of tables
        tables_to_drop = [model.__table__ for model in MODELS_TO_DROP]
        db.metadata.drop_all(bind=db.engine, tables=tables_to_drop)
        print("Selected tables dropped successfully.")
        
        # 2. Re-create ONLY the dropped tables
        print(f"Re-creating tables: {[model.__tablename__ for model in MODELS_TO_DROP]}...")
        
        # We use db.metadata.create_all() with the same list of tables
        tables_to_create = [model.__table__ for model in MODELS_TO_DROP]
        db.metadata.create_all(bind=db.engine, tables=tables_to_create)
        print("Selected tables re-created successfully.")
        
        print(f"\nNOTE: The tables '{AppSetting.__tablename__}' and '{FixedBill.__tablename__}' were NOT touched.")
        print("--- Selective Database Reset Complete! ---")

if __name__ == '__main__':
    # Add a safety check before running!
    confirm = input("Are you absolutely sure you want to EMPTY all data EXCEPT AppSetting and FixedBill? (Type 'YES' to proceed): ")
    if confirm.upper() == 'YES':
        reset_database_selective()
    else:
        print("Operation cancelled. No changes were made to the database.")