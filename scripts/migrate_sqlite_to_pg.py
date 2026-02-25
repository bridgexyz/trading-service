#!/usr/bin/env python3
"""One-time migration script: copy data from SQLite to PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_pg.py <sqlite_path> <postgres_url>

Example:
    python scripts/migrate_sqlite_to_pg.py \
        data/trading.db \
        postgresql://trading:trading_secret@localhost:5432/trading
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


# Tables ordered by FK dependencies (parents first)
TABLE_ORDER = [
    "user",
    "credential",
    "trading_pair",
    "open_position",
    "trade",
    "equity_snapshot",
    "job_log",
]


def migrate(sqlite_path: str, pg_url: str):
    if not Path(sqlite_path).exists():
        print(f"ERROR: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    sqlite_url = f"sqlite:///{sqlite_path}"
    src = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    dst = create_engine(pg_url)

    src_inspector = inspect(src)
    src_tables = set(src_inspector.get_table_names())

    # Ensure target schema exists (create tables via SQLModel first)
    print("Creating PostgreSQL schema...")
    # Import all models so metadata is populated
    from backend.models import (  # noqa: F401
        TradingPair, Trade, OpenPosition, EquitySnapshot, JobLog, Credential, User,
    )
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(dst)

    dst_inspector = inspect(dst)
    dst_tables = set(dst_inspector.get_table_names())

    for table_name in TABLE_ORDER:
        if table_name not in src_tables:
            print(f"  SKIP {table_name} (not in SQLite)")
            continue
        if table_name not in dst_tables:
            print(f"  SKIP {table_name} (not in PostgreSQL schema)")
            continue

        # Read all rows from SQLite
        with src.connect() as src_conn:
            rows = src_conn.execute(text(f"SELECT * FROM \"{table_name}\"")).mappings().all()

        if not rows:
            print(f"  {table_name}: 0 rows (empty)")
            continue

        columns = list(rows[0].keys())
        col_list = ", ".join(f'"{c}"' for c in columns)
        param_list = ", ".join(f":{c}" for c in columns)
        insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({param_list})'

        with dst.connect() as dst_conn:
            # Clear existing data in target table
            dst_conn.execute(text(f'DELETE FROM "{table_name}"'))
            dst_conn.execute(text(insert_sql), [dict(row) for row in rows])

            # Reset sequence for tables with an id column
            if "id" in columns:
                max_id = max(row["id"] for row in rows if row["id"] is not None)
                seq_name = f"{table_name}_id_seq"
                try:
                    dst_conn.execute(text(f"SELECT setval('{seq_name}', :val)"), {"val": max_id})
                except Exception:
                    # Sequence might not exist or have a different name
                    pass

            dst_conn.commit()

        print(f"  {table_name}: {len(rows)} rows migrated")

    print("\nMigration complete!")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    migrate(sys.argv[1], sys.argv[2])
