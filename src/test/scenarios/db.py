"""Connection to the devcontainer Postgres through environment variables (.env).

Reuses `snakeorm.config.dsn_from_env` (the SAME logic the CLI uses) so that neither the variable
names nor the devcontainer defaults get duplicated. The defaults match
`.devcontainer/docker-compose.yml`: it works as-is inside the devcontainer (DB_HOST=db) and on the
host (DB_HOST=127.0.0.1 through the mapped port). A short `connect_timeout` so the tests skip
quickly when there is no DB.
"""

from __future__ import annotations

from snakeorm.core.config import dsn_from_env


def dsn() -> str:
    """Builds the psycopg2 DSN from .env / the environment, with devcontainer defaults."""
    return dsn_from_env(connect_timeout=2)
