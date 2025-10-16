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

def reset_database():
    """Drops all tables and re-creates them."""
    with app.app_context():
        print("--- Starting Database Reset ---")
        
        # 1. Drop all existing tables (Empty all data)
        print("Dropping all existing tables...")
        db.drop_all()
        print("All tables dropped successfully.")
        
        # 2. Re-create all tables based on the models
        print("Creating new tables...")
        db.create_all()
        print("All tables re-created successfully.")
        
        print("--- Database Reset Complete! Your tables are now empty. ---")

if __name__ == '__main__':
    # Add a safety check before running!
    confirm = input("Are you absolutely sure you want to EMPTY all data from the database? (Type 'YES' to proceed): ")
    if confirm.upper() == 'YES':
        reset_database()
    else:
        print("Operation cancelled. No changes were made to the database.")