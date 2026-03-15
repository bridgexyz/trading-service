"""Add fill price columns to open_position table.

Run with: python migrations/add_fill_prices.py
"""

import sqlite3
import os

DB_PATH = os.environ.get("TS_DATABASE_URL", "sqlite:///data/trading.db")
# Extract file path from sqlite URL
db_file = DB_PATH.replace("sqlite:///", "")

def migrate():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Check which columns already exist
    cursor.execute("PRAGMA table_info(open_position)")
    existing = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("fill_price_a", "REAL"),
        ("fill_price_b", "REAL"),
        ("fill_amount_a", "REAL"),
        ("fill_amount_b", "REAL"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE open_position ADD COLUMN {col_name} {col_type}")
            print(f"Added column: {col_name}")
        else:
            print(f"Column already exists: {col_name}")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
