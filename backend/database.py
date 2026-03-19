"""SQLModel database engine and session management."""

import logging

from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine, Session

from backend.config import settings

logger = logging.getLogger(__name__)

# SQLite needs check_same_thread=False; PostgreSQL does not
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)


def _run_migrations():
    """Run lightweight schema migrations for column renames."""
    from sqlalchemy import text

    inspector = inspect(engine)

    # Check if trading_pair table exists before migrating
    if "trading_pair" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("trading_pair")}
    if "position_size" in columns and "position_size_pct" not in columns:
        logger.info("Migrating: renaming position_size -> position_size_pct")
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE trading_pair RENAME COLUMN position_size TO position_size_pct")
            )
            conn.commit()

    # Add slice_chunks and slice_delay_sec columns for sliced order mode
    if "slice_chunks" not in columns:
        logger.info("Migrating: adding slice_chunks column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE trading_pair ADD COLUMN slice_chunks INTEGER NOT NULL DEFAULT 10"))
            conn.commit()
    if "slice_delay_sec" not in columns:
        logger.info("Migrating: adding slice_delay_sec column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE trading_pair ADD COLUMN slice_delay_sec REAL NOT NULL DEFAULT 2.0"))
            conn.commit()

    # Add credential_id column for per-pair credential assignment
    if "credential_id" not in columns:
        logger.info("Migrating: adding credential_id column to trading_pair")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE trading_pair ADD COLUMN credential_id INTEGER REFERENCES credential(id)"))
            conn.commit()

    # Migrate credential.account_index from INTEGER to TEXT for large values
    if "credential" in inspector.get_table_names():
        cred_columns = {col["name"]: col for col in inspector.get_columns("credential")}
        if "account_index" in cred_columns:
            col_type = str(cred_columns["account_index"]["type"]).upper()
            if "INT" in col_type:
                logger.info("Migrating: credential.account_index INTEGER -> TEXT")
                with engine.connect() as conn:
                    if settings.database_url.startswith("sqlite"):
                        # SQLite: rename table, recreate, copy data
                        conn.execute(text("ALTER TABLE credential RENAME TO credential_old"))
                        conn.execute(text(
                            "CREATE TABLE credential ("
                            "id INTEGER PRIMARY KEY, name VARCHAR, lighter_host VARCHAR, "
                            "api_key_index INTEGER, private_key_encrypted VARCHAR, "
                            "account_index VARCHAR NOT NULL DEFAULT '0', "
                            "is_active BOOLEAN, created_at TIMESTAMP)"
                        ))
                        conn.execute(text(
                            "INSERT INTO credential SELECT id, name, lighter_host, "
                            "api_key_index, private_key_encrypted, CAST(account_index AS VARCHAR), "
                            "is_active, created_at FROM credential_old"
                        ))
                        conn.execute(text("DROP TABLE credential_old"))
                    else:
                        conn.execute(text(
                            "ALTER TABLE credential "
                            "ALTER COLUMN account_index TYPE VARCHAR USING account_index::VARCHAR"
                        ))
                    conn.commit()

    # Add exit_schedule_interval and use_exit_schedule columns
    if "exit_schedule_interval" not in columns:
        logger.info("Migrating: adding exit_schedule_interval column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE trading_pair ADD COLUMN exit_schedule_interval VARCHAR NOT NULL DEFAULT '15m'"))
            conn.commit()
    if "use_exit_schedule" not in columns:
        logger.info("Migrating: adding use_exit_schedule column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE trading_pair ADD COLUMN use_exit_schedule BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()

    # Ensure unique constraint on open_position.pair_id
    if "open_position" in inspector.get_table_names():
        existing_indexes = inspector.get_indexes("open_position")
        has_unique_idx = any(
            idx["name"] == "ix_open_position_pair_id_unique" for idx in existing_indexes
        )
        if not has_unique_idx:
            with engine.connect() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX ix_open_position_pair_id_unique "
                    "ON open_position (pair_id)"
                ))
                conn.commit()


def create_db_and_tables():
    """Create all tables. Called on startup."""
    SQLModel.metadata.create_all(engine)
    _run_migrations()


def get_session() -> Session:
    """Dependency that yields a database session."""
    with Session(engine) as session:
        yield session
