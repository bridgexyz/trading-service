"""SQLModel database engine and session management."""

import logging
from collections.abc import AsyncGenerator

from sqlmodel import SQLModel, create_engine, Session

from backend.config import settings

logger = logging.getLogger(__name__)

# Strip sqlite:/// prefix and re-add for proper path handling
engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def _run_migrations():
    """Run lightweight schema migrations for column renames."""
    from sqlalchemy import text

    with engine.connect() as conn:
        # Check if old column exists and rename it
        result = conn.execute(text("PRAGMA table_info(trading_pair)"))
        columns = {row[1] for row in result}
        if "position_size" in columns and "position_size_pct" not in columns:
            logger.info("Migrating: renaming position_size -> position_size_pct")
            conn.execute(
                text("ALTER TABLE trading_pair RENAME COLUMN position_size TO position_size_pct")
            )
            conn.commit()

        # Ensure unique constraint on open_position.pair_id (defense against duplicate positions)
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_open_position_pair_id_unique "
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
