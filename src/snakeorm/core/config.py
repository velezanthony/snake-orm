"""The one place that turns the environment (`.env` included) into a psycopg2 DSN; shared by CLI
and tests.

`find_dotenv(usecwd=True)`: a bare `load_dotenv()` searches from the calling file, which with the
package installed would point at `site-packages`; anchoring it to the cwd is what the user expects.
"""

from __future__ import annotations

import os
import re

from dotenv import find_dotenv, load_dotenv

from snakeorm.core.exceptions import SnakeConfigError

# Each piece of the DSN: (environment variable, key in the DSN, devcontainer default).
# The order fixes the order of the emitted DSN; it is the ONLY source of the names and defaults.
_PARTS: tuple[tuple[str, str, str], ...] = (
    ("DB_HOST", "host", "127.0.0.1"),
    ("DB_PORT", "port", "5432"),
    ("DB_USER", "user", "postgres"),
    ("DB_PASSWORD", "password", "snakeorm_pass"),
    ("DB_NAME", "dbname", "snakeorm_db"),
)

# Environment variables that describe the connection (derived from _PARTS, no duplication).
DB_ENV_KEYS: tuple[str, ...] = tuple(env_key for env_key, _, _ in _PARTS)


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
"""The RFC 3986 shape of a scheme, and a regex rather than `split("://", 1)`.

A password containing `://` would otherwise be read as the scheme — the same failure this guard is
about, arriving through a value nobody thinks of as configuration."""


def load_env() -> None:
    """Loads the cwd's `.env` (or an ancestor's), without stomping on variables already present
    (the environment wins)."""
    path = find_dotenv(
        usecwd=True
    )  # empty string if there is no .env in the cwd's tree
    if path:
        load_dotenv(path)


def dsn_from_env(*, connect_timeout: int | None = None) -> str:
    """Builds the psycopg2 DSN from `.env`/environment, with the devcontainer defaults.

    `connect_timeout` adds the parameter of the same name when given (the tests lower it so they do
    not hang).
    """
    load_env()
    parts = [
        f"{dsn_key}={os.environ.get(env_key, default)}"
        for env_key, dsn_key, default in _PARTS
    ]
    if connect_timeout is not None:
        parts.append(f"connect_timeout={connect_timeout}")
    return " ".join(parts)


# -- NAMED connections (multi-DB) ------------------------------------------------------------
# Here we only resolve WHICH DSN belongs to each name; `snake_session(...)` assembles the driver.
# `default` resolves as always (a single-DB project changes nothing); the rest through
# `SNAKEORM_DSN_<NAME>` in uppercase.

DEFAULT_DATABASE = "default"


def _env_key(database: str) -> str:
    """The environment variable that declares a named connection's DSN."""
    return f"SNAKEORM_DSN_{database.upper()}"


def dsn_for(database: str = DEFAULT_DATABASE) -> str:
    """DSN of a connection BY NAME.

    `default` falls into the usual resolution; any other name is looked up in
    `SNAKEORM_DSN_<NAME>`, and if it is missing we say EXACTLY which one: resolving blindly ends up
    connecting to the wrong DB.
    """
    if database == DEFAULT_DATABASE:
        return dsn_from_env()
    load_env()
    value = os.environ.get(_env_key(database))
    if not value:
        raise SnakeConfigError(
            f"There is no DSN for connection '{database}': set the environment variable "
            f"{_env_key(database)} (or put it in the .env). Connection '{DEFAULT_DATABASE}' is the "
            f"only one resolved from the DB_* pieces."
        )
    return value


_BACKEND_DEFAULT_KEY = "DB_BACKEND"
"""The engine of the DEFAULT connection, beside the `DB_*` pieces that build its DSN.

The name is not invented here: `frameworks/shared/config.py` already reads it, because the demos
needed to pick an engine and the ORM offered nowhere to say so. That is the asymmetry this closes —
the convention existed, it just lived in the showcase instead of the library.
"""

_BACKEND_NAMES: dict[str, str] = {
    # DSN scheme -> engine. It is a DECLARATION, not a guess: whoever writes `mysql://` said which
    # engine they meant, and reading it is not divination.
    "postgresql": "postgres",
    "postgres": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "sqlite": "sqlite",
}

_KNOWN_BACKENDS = ("postgres", "mysql", "sqlite")


def _backend_key(database: str) -> str:
    """The environment variable that declares a named connection's ENGINE."""
    return f"SNAKEORM_BACKEND_{database.upper()}"


def backend_name_for(database: str = DEFAULT_DATABASE) -> str:
    """The engine of a connection BY NAME, as a plain string. It is READ, never guessed.

    1. `SNAKEORM_BACKEND_<NAME>` — or `DB_BACKEND` for the default connection — which always wins:
       saying it out loud beats inferring it.
    2. The DSN's own scheme (`postgresql://`, `mysql://`, `sqlite://`).
    3. Postgres, when the DSN carries NO scheme. That is a derivation and not a fallback: a DSN
       shaped `host=x dbname=y` is libpq keyword syntax, which no other engine speaks.

    A value that is not one of the three is REFUSED naming what it read. The demos already paid for
    the alternative and wrote it down: a `postgress` with one extra `s` brought the app up on SQLite,
    talking to the wrong database without a word.

    It returns a `str` and not a `SnakeBackend` on purpose: `connection.py` — where that enum lives —
    sits ABOVE this module and pulls in every driver and dialect. Importing it from here would close
    a circle between the layers, and the acyclicity net says so.
    """
    load_env()
    key = (
        _BACKEND_DEFAULT_KEY if database == DEFAULT_DATABASE else _backend_key(database)
    )
    declared = os.environ.get(key, "").strip().lower()
    if declared:
        if declared not in _KNOWN_BACKENDS:
            raise SnakeConfigError(
                f"{key}='{declared}' is not a known engine. The three are: "
                f"{', '.join(_KNOWN_BACKENDS)}. It is refused instead of falling back, because "
                f"falling back means talking to another database without saying so."
            )
        return declared
    dsn = dsn_for(database)
    match = _SCHEME.match(dsn)
    if match is None:
        # NO scheme is the libpq keyword/value form (`host=x dbname=y`), which is Postgres and is
        # not an error. This is the case the fallback existed for.
        return "postgres"
    scheme = match.group(1).lower()
    if scheme not in _BACKEND_NAMES:
        # And an UNKNOWN scheme is refused, for the reason written fifteen lines above about
        # `DB_BACKEND`: falling back means talking to another database without saying so. The old
        # `.get(scheme, "postgres")` could not tell the two cases apart, so `sqlite3://` —the name
        # of the Python module, and an alias `contrib/config.py` accepts elsewhere— came out as
        # Postgres. Same class of typo, two opposite treatments, in the one function that decides
        # which engine you are talking to.
        raise SnakeConfigError(
            f"The DSN of '{database}' starts with '{scheme}://', which is not an engine this ORM "
            f"knows. The schemes it reads are: {', '.join(sorted(_BACKEND_NAMES))}. A DSN with no "
            f"scheme at all is the libpq keyword/value form and resolves to postgres; a scheme it "
            f"does not recognise is refused rather than guessed at."
        )
    return _BACKEND_NAMES[scheme]
