"""A write of this ORM inside a Django `atomic()` goes on ANOTHER connection, so it is refused.

Measured against a live PostgreSQL, inside `transaction.atomic()`:

    Django    -> PID 49068  txid 57694
    snake-orm -> PID 49069  txid 57695

Two connections, two transactions. A write of ours in there SURVIVES Django's rollback: the block
reverts what Django wrote and keeps what we wrote. It does not fail — it stains, and only on the
error path, which is the least exercised path of any codebase.

Until the connection can be borrowed, the honest answer is to refuse, loudly, at the seam every
write crosses.
"""

from __future__ import annotations

from typing import Any

import pytest

from snakeorm.contrib.django import SnakeAtomicGuardDriver
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.drivers import SnakeDriver


class _Spy:
    """A driver that records what reached it, so a pass-through can be told from a refusal."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def fetch_all(self, sql: str, params: Any) -> list[tuple[object, ...]]:
        self.seen.append("fetch_all")
        return []

    def fetch_iter(self, sql: str, params: Any, *, chunk: int = 1000) -> Any:
        self.seen.append("fetch_iter")
        return iter(())

    def execute(self, sql: str, params: Any) -> int:
        self.seen.append("execute")
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self.seen.append("commit")

    def rollback(self) -> None:
        self.seen.append("rollback")

    def savepoint(self, name: str) -> None:
        self.seen.append("savepoint")

    def release_savepoint(self, name: str) -> None:
        self.seen.append("release_savepoint")

    def rollback_to_savepoint(self, name: str) -> None:
        self.seen.append("rollback_to_savepoint")

    def close(self) -> None:
        self.seen.append("close")


def test_a_write_is_refused_and_the_message_says_why() -> None:
    """Inside the block, `execute` is refused, and the refusal names the two connections."""
    spy = _Spy()
    guarded = SnakeAtomicGuardDriver(spy, in_atomic=lambda: True)

    with pytest.raises(SnakeUnsupportedFeature) as caught:
        guarded.execute("UPDATE t SET a = 1", ())

    assert "atomic()" in str(caught.value)
    assert spy.seen == []


def test_reading_is_left_alone() -> None:
    """A read inside the block is fine and must keep working: the migration reads inside views.

    Refusing everything would be easier and would break the half that is already correct.
    """
    spy = _Spy()
    guarded = SnakeAtomicGuardDriver(spy, in_atomic=lambda: True)

    guarded.fetch_all("SELECT 1", ())
    list(guarded.fetch_iter("SELECT 1", ()))

    assert spy.seen == ["fetch_all", "fetch_iter"]


def test_outside_the_block_nothing_is_refused() -> None:
    """With no `atomic()` open the guard is transparent, including its own transaction control."""
    spy = _Spy()
    guarded = SnakeAtomicGuardDriver(spy, in_atomic=lambda: False)

    guarded.execute("UPDATE t SET a = 1", ())
    guarded.commit()

    assert spy.seen == ["execute", "commit"]


def test_transaction_control_is_refused_too() -> None:
    """Committing OUR connection inside Django's block is the same defect wearing another hat."""
    guarded = SnakeAtomicGuardDriver(_Spy(), in_atomic=lambda: True)

    for call, what in ((guarded.commit, "A commit"), (guarded.rollback, "A rollback")):
        with pytest.raises(SnakeUnsupportedFeature) as caught:
            call()
        assert str(caught.value).startswith(what)
        assert "atomic()" in str(caught.value)


def test_every_writing_method_of_the_protocol_is_guarded() -> None:
    """The net that cannot go stale: the guarded surface is DERIVED from `SnakeDriver`, not listed.

    A hand-written list of what writes is a list that stops matching the protocol the day somebody
    adds a method to it — and the new one would pass through in silence, which is the defect this
    whole file exists to prevent. Reads and `close` are the only things that may cross.
    """
    allowed = {"fetch_all", "fetch_iter", "last_insert_id", "close"}
    protocol = {
        name
        for name in vars(SnakeDriver)
        if not name.startswith("_") and callable(getattr(SnakeDriver, name, None))
    }
    guarded = SnakeAtomicGuardDriver(_Spy(), in_atomic=lambda: True)

    unguarded = sorted(
        name for name in protocol - allowed if not _refuses(guarded, name)
    )

    assert unguarded == [], (
        f"these methods of `SnakeDriver` reach the connection inside a Django `atomic()`: "
        f"{unguarded}. Either guard them, or add them to `allowed` above WITH the reason they may."
    )


def _refuses(driver: SnakeAtomicGuardDriver, name: str) -> bool:
    """Whether calling `name` on the guard raises instead of reaching the wrapped driver."""
    method = getattr(driver, name, None)
    if method is None:
        return False
    try:
        method(*_ARGS.get(name, ()))
    except SnakeUnsupportedFeature:
        return True
    except TypeError:
        return False
    return False


_ARGS: dict[str, tuple[object, ...]] = {
    "execute": ("UPDATE t SET a = 1", ()),
    "savepoint": ("sp",),
    "release_savepoint": ("sp",),
    "rollback_to_savepoint": ("sp",),
}
