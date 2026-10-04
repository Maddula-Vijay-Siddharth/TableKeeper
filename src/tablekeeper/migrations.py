from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session


MIGRATION_DIR = Path(__file__).with_name("migrations")


def apply_migrations(db: Session) -> None:
    db.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY)"))
    for migration in sorted(MIGRATION_DIR.glob("*.sql")):
        version = migration.name
        exists = db.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": version},
        ).scalar()
        if exists:
            continue
        connection = db.connection().connection
        with connection.cursor() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8"))
        db.execute(text("INSERT INTO schema_migrations(version) VALUES (:version)"), {"version": version})
    db.commit()
