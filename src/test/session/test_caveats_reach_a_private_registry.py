"""The fidelity caveats reach a project built on `@snake_model(registry=...)`.

`_declared_python_types` enumerates the GLOBAL registry, so a project whose models all live in a
private one gets NO type caveats at all: the advisor walks an empty list and says nothing, and
saying nothing is exactly what this warning exists to stop. The one thing this ORM never does is
store worse and keep quiet about it.

It is the quiet end of a defect the rest of the audit fixed loudly. Everywhere else, resolving
against the wrong registry either raised or returned the wrong table; here it just... does not warn.

The session takes the registry to enumerate, and `SnakeConnection.session()` passes it on. That
second half is not optional: a project using the connection helper — which is the recommended way in
the guide — would otherwise still get half a warning, and half a warning is worse than none because
it reads as "there is nothing else to tell you".
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator, Sequence
from decimal import Decimal

import pytest

from snakeorm.core.exceptions import SnakeWarning
from snakeorm.decorators import snake_model
from snakeorm.dialects import SQLiteDialect
from snakeorm.fields import SnakeColumn, snake_decimal, snake_int
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.registry import SnakeRegistry
from snakeorm.session import SnakeSession

_PRIVATE = SnakeRegistry()


@snake_model(table="cav_prices", registry=_PRIVATE)
class _Price(SnakeModel):
    """A model with a `Decimal`, which is a type SQLite degrades and Postgres does not."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    amount: SnakeColumn[Decimal] = snake_decimal(precision=10, scale=2)


snake_link(_PRIVATE)


class _Driver:
    """A driver that does nothing: the warning happens at construction, before any query."""

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return []

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from ()

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


@pytest.fixture(autouse=True)
def _forget_what_was_already_said() -> Iterator[None]:
    """Clears the ONCE-per-process dedup around each test.

    `_warned_caveats` is deliberately per PROCESS —"a seeding run does dozens of `add_all`s; one
    warning per batch is noise"— so by the time this file runs, another test has already opened a
    SQLite session and every caveat is suppressed. A test about the CONTENT of the warning has to
    reset it, and put it back so it does not change what the rest of the suite sees.
    """
    from snakeorm.session import shared as session_mod

    saved = set(session_mod._warned_caveats)
    session_mod._warned_caveats.clear()
    yield
    session_mod._warned_caveats.clear()
    session_mod._warned_caveats.update(saved)


def _caveats(**kwargs: object) -> list[str]:
    """The ORM's own warnings raised while opening a session over SQLite."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        SnakeSession(_Driver(), SQLiteDialect(), **kwargs)  # type: ignore[arg-type]
    return [
        str(entry.message)
        for entry in captured
        if issubclass(entry.category, SnakeWarning)
    ]


def test_a_decimal_in_a_private_registry_still_gets_its_caveat() -> None:
    """SQLite degrades `Decimal`, and the user has to hear it wherever their models live."""
    said = _caveats(model_registry=_PRIVATE)

    assert any("Decimal" in message for message in said), (
        "the advisor enumerated the global registry, found nothing, and said nothing at all"
    )


def test_the_advisor_still_defaults_to_the_global_registry() -> None:
    """The floor: a session opened the usual way keeps working exactly as before.

    The parameter is an addition, not a requirement — almost every project has one registry and
    should not have to name it.
    """
    said = _caveats()

    assert any("SQLiteDialect" in message for message in said), (
        "the structural caveats stopped coming out of a plain session"
    )


def test_a_caveat_about_a_type_nobody_declares_is_not_raised() -> None:
    """And the filtering still works over the registry it was given.

    The advisor only mentions a type some model USES — telling somebody what happens to an `Interval`
    when they have none is noise, and noise ends in a `filterwarnings("ignore")` that also takes down
    the warnings that mattered. That reasoning has to survive the change of registry, or the fix
    trades silence for a wall of text.
    """
    said = " ".join(_caveats(model_registry=_PRIVATE))

    assert "interval" not in said.lower(), (
        "it warned about a type this registry never declares"
    )
