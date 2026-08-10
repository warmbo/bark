"""Read-only SQLite access to bark's database.

The engine never writes to bark's DB. Connections use ``mode=ro`` so even a
buggy query cannot mutate it.
"""

from __future__ import annotations

import sqlalchemy as sa


def connect_readonly(db_path: str) -> sa.Engine:
    """Open a read-only connection to a SQLite file."""
    url = f"sqlite:///file:{db_path}?mode=ro&uri=true"
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


def fetch_all(engine: sa.Engine, sql: str, **params) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text(sql), params).mappings().all()
        return [dict(r) for r in rows]


def fetch_one(engine: sa.Engine, sql: str, **params) -> dict | None:
    rows = fetch_all(engine, sql, **params)
    return rows[0] if rows else None
