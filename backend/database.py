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
