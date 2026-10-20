"""SQLite database setup and schema versioning."""

from __future__ import annotations

from pathlib import Path

from peewee import SqliteDatabase

from smurfsniper.logger import logger
from smurfsniper.storage.migrations import MIGRATIONS


def schema_version(db: SqliteDatabase) -> int:
    db.execute_sql("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = db.execute_sql("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def migrate(db: SqliteDatabase) -> int:
    """Run pending migrations, each in its own transaction. Returns the new version."""
    current = schema_version(db)
    for version, step in enumerate(MIGRATIONS[current:], start=current + 1):
        with db.atomic():
            step(db)
            db.execute_sql("DELETE FROM schema_version")
            db.execute_sql("INSERT INTO schema_version (version) VALUES (?)", (version,))
        logger.info(f"player log schema migrated to v{version} ({step.__name__})")
    return max(current, len(MIGRATIONS))


def init_db(path: Path) -> SqliteDatabase:
    """Open (creating if needed) the database at ``path`` and migrate it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = SqliteDatabase(
        str(path),
        pragmas={"journal_mode": "wal", "foreign_keys": 1, "cache_size": -16000},
        check_same_thread=False,
    )
    db.connect(reuse_if_open=True)
    migrate(db)
    return db
