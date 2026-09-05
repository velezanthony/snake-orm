"""Session factory keyed by connection NAME."""

from __future__ import annotations

from snakeorm.core.config import DEFAULT_DATABASE, backend_name_for, dsn_for
from snakeorm.session.session import SnakeSession


def snake_session(database: str = DEFAULT_DATABASE) -> SnakeSession:
    """Opens a session against the connection with that name, resolving the DSN by configuration.

    A single path for the common case (multi-DB). Whoever needs to decorate the driver (logging,
    pool, timeout) still builds the session by hand: this is convenience, not a replacement for the
    seam.

    Pairing driver and dialect is delegated to `SnakeConnectionConfig`, which exists precisely so
    that a driver cannot be put together with another engine's dialect. Two composition roots are
    one too many: the one nobody reviews is the one that ends up lying. The engine is READ like the
    DSN is (see `backend_name_for`); hardcoding it would reach only one of the three.
    """
    # Lazy, and not for performance: `connection.py` imports `session` so it can return a session,
    # so importing it up top would close the cycle. That is the natural direction — the connection
    # config sits ABOVE the session, not the other way around — and this function is the
    # convenience exception that swims against it.
    from snakeorm.connection import SnakeBackend, SnakeConnectionConfig

    return SnakeConnectionConfig.from_dsn(
        dsn_for(database), SnakeBackend(backend_name_for(database))
    ).open()
