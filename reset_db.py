"""
Reset the local SQLite database.

Drops and recreates the tables for the two surviving models
(AppSetting, DailyPaidItem).
"""
from main import app, db

if __name__ == "__main__":
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Local SQLite reset: AppSetting, DailyPaidItem.")
