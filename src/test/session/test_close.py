"""`SnakeSession.close()`: the synchronous session can now return the connection to the pool.

The review found that the sync session had no `close()` (the async one did): with a `PooledDriver`,
the borrowed connection had no way back to the pool. Now `close()` closes the driver —which with a
pool means RETURNING the connection—, symmetric to `AsyncSession.close()`. `__exit__` does not call
it on purpose: the driver is injected and its lifecycle belongs to whoever created it.
"""

from __future__ import annotations

from snakeorm import PostgresDialect, SnakeSession


class _DriverEspia:
    """Fake driver that notes down whether it was asked to close."""

    def __init__(self) -> None:
        self.cerrado = False

    def close(self) -> None:
        self.cerrado = True

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


def test_close_delegates_to_the_driver() -> None:
    """Verifies that `session.close()` closes the driver (with a pool = return the connection)."""
    driver = _DriverEspia()
    session = SnakeSession(driver, PostgresDialect())  # type: ignore[arg-type]
    assert driver.cerrado is False
    session.close()
    assert driver.cerrado is True


def test_exit_does_not_close_the_injected_driver() -> None:
    """Verifies that leaving the `with` does NOT close the driver: its lifecycle
    belongs to whoever injected it.
    """
    driver = _DriverEspia()
    with SnakeSession(driver, PostgresDialect()):  # type: ignore[arg-type]
        pass
    assert driver.cerrado is False  # commit/rollback yes, close NO
