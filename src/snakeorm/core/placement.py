"""The two axes that place a table: in WHICH database and in WHICH schema (their defaults).

No imports on purpose: half the codebase reads it (metadata, compiler, decorators, migrations,
CLI), so any import of its own would be a cycle — and putting it in `config.py` would drag `dotenv`
into everyone who touches a table.
"""

from __future__ import annotations

DEFAULT_SCHEMA = "public"
"""A table's default schema. Postgres's; SQLite ignores it (it has no schemas)."""

DEFAULT_DATABASE = "default"
"""The default connection. Resolved through `DATABASE_URL`/`SNAKEORM_DSN`/`DB_*`; every other one
through `SNAKEORM_DSN_<NAME>`."""
