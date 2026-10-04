from __future__ import annotations

from .database import SessionLocal
from .migrations import apply_migrations


def main() -> None:
    with SessionLocal() as db:
        apply_migrations(db)
    print("Tablekeeper migrations applied.")
