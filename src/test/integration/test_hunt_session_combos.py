"""HUNT 5 — the session with the NEW stuff on top: enums on every write and read path.

`add`, `add_all`, `upsert`, `update`, `annotate` and the prefetch were built BEFORE the enums, and
each one has its own path for the values. `add` is already tested with enums; the others are not.
A `to_db` missing on just one of those paths is a silent failure: the row goes in with rubbish or
the query finds nothing at all.

And the three driver decorators, stacked. Each one has its test; nobody has put them together, and
a decorator that swallows a method breaks the ones underneath without saying a word.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import IntEnum, StrEnum

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    LoggingDriver,
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    TimeoutDriver,
    count,
    snake_enum,
    snake_int,
    snake_model,
    snake_table,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


class Color(StrEnum):
    """Enum de texto."""

    ROJO = "rojo"
    AZUL = "azul"


class Talla(IntEnum):
    """Enum numérico."""

    S = 1
    L = 3


@snake_model(table="combo_prendas")
class Prenda(SnakeModel):
    """Garment with two enums, so as to walk every path of the session."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    color: SnakeColumn[Color] = snake_enum(Color, default=Color.ROJO)
    talla: SnakeColumn[Talla] = snake_enum(Talla, default=Talla.S)


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session with the FULL STACK of decorators: timeout over logging over the real driver."""
    import psycopg2

    try:
        raw = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    lines: list[str] = []
    driver = TimeoutDriver(
        LoggingDriver(raw, write=lines.append),
        PostgresDialect(),
        statement_timeout_ms=5000,
    )
    driver.execute("DROP TABLE IF EXISTS combo_prendas CASCADE", ())
    driver.execute(emit_create_table(snake_table(Prenda), PostgresDialect()), ())
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS combo_prendas CASCADE", ())
        driver.commit()
        driver.close()


def test_the_decorator_stack_behaves_like_a_plain_driver(session: SnakeSession) -> None:
    """The three of them stacked have to behave EXACTLY like the driver underneath."""
    session.add(Prenda(id=1, color=Color.AZUL, talla=Talla.L))
    session.commit()

    found = session.first(SnakeQuery(Prenda).filter(Prenda.id == 1))
    assert found is not None and found.color is Color.AZUL


def test_add_all_carries_the_enum_values(session: SnakeSession) -> None:
    """`add_all` has its OWN path for values (a multiple INSERT), different from `add`'s."""
    session.add_all(
        [
            Prenda(id=1, color=Color.ROJO, talla=Talla.S),
            Prenda(id=2, color=Color.AZUL, talla=Talla.L),
        ]
    )
    session.commit()

    rows = session._driver.fetch_all(  # noqa: SLF001
        "SELECT id, color, talla FROM combo_prendas ORDER BY id", ()
    )
    assert rows == [(1, "rojo", 1), (2, "azul", 3)]


def test_upsert_carries_the_enum_values(session: SnakeSession) -> None:
    """`upsert` is yet another path (`ON CONFLICT ... DO UPDATE`)."""
    session.add(Prenda(id=1, color=Color.ROJO, talla=Talla.S))
    session.commit()

    session.upsert(
        Prenda(id=1, color=Color.AZUL, talla=Talla.L),
        on_conflict=[Prenda.id],
        update=[Prenda.color, Prenda.talla],
    )
    session.commit()

    updated = session.first(SnakeQuery(Prenda).filter(Prenda.id == 1))
    assert updated is not None
    assert updated.color is Color.AZUL and updated.talla is Talla.L


def test_update_carries_the_enum_values(session: SnakeSession) -> None:
    """`update` by PK: the SET has its own path for values."""
    garment = session.add(Prenda(id=1, color=Color.ROJO, talla=Talla.S))
    session.commit()

    garment.color = Color.AZUL
    session.update(garment)
    session.commit()

    assert session._driver.fetch_all(  # noqa: SLF001
        "SELECT color FROM combo_prendas WHERE id = 1", ()
    ) == [("azul",)]


def test_bulk_update_where_carries_the_enum_values(session: SnakeSession) -> None:
    """The BULK write: values in the SET and in the WHERE, both of them with enums."""
    session.add_all(
        [
            Prenda(id=1, color=Color.ROJO, talla=Talla.S),
            Prenda(id=2, color=Color.AZUL, talla=Talla.S),
        ]
    )
    session.commit()

    # `values` are PAIRS, not a dict: `SnakeExpr` is not hashable on purpose —its `__eq__`
    # builds a condition, so a hash by identity would be incoherent—.
    affected = session.update_where(
        SnakeQuery(Prenda).filter(Prenda.color == Color.ROJO), [(Prenda.talla, Talla.L)]
    )
    session.commit()

    assert affected == 1, "the WHERE by enum has to find the row"
    assert session._driver.fetch_all(  # noqa: SLF001
        "SELECT talla FROM combo_prendas WHERE id = 1", ()
    ) == [(3,)]


def test_delete_where_carries_the_enum_values(session: SnakeSession) -> None:
    """The bulk delete filtering by enum."""
    session.add_all(
        [
            Prenda(id=1, color=Color.ROJO, talla=Talla.S),
            Prenda(id=2, color=Color.AZUL, talla=Talla.S),
        ]
    )
    session.commit()

    deleted = session.delete_where(
        SnakeQuery(Prenda).filter(Prenda.color == Color.AZUL)
    )
    session.commit()

    assert deleted == 1
    assert session.count(SnakeQuery(Prenda)) == 1


def test_projection_and_aggregation_over_an_enum(session: SnakeSession) -> None:
    """Projecting and grouping BY an enum: the way back goes through another coercion path."""
    session.add_all(
        [
            Prenda(id=1, color=Color.ROJO, talla=Talla.S),
            Prenda(id=2, color=Color.ROJO, talla=Talla.L),
            Prenda(id=3, color=Color.AZUL, talla=Talla.S),
        ]
    )
    session.commit()

    rows = session.select(
        SnakeQuery(Prenda).group_by(Prenda.color).order_by(Prenda.color),
        Prenda.color,
        count(),
    )
    assert rows == [(Color.AZUL, 1), (Color.ROJO, 2)], (
        "the enum comes back in a projection too"
    )


def test_get_or_create_with_enums(session: SnakeSession) -> None:
    """`get_or_create` filters and builds: both sides with enums."""
    _, created = session.get_or_create(
        SnakeQuery(Prenda).filter(Prenda.color == Color.AZUL),
        lambda: Prenda(id=1, color=Color.AZUL, talla=Talla.L),
    )
    session.commit()
    assert created is True

    _, again = session.get_or_create(
        SnakeQuery(Prenda).filter(Prenda.color == Color.AZUL),
        lambda: Prenda(id=2, color=Color.AZUL, talla=Talla.S),
    )
    assert again is False, "the filter by enum has to find the one that already exists"


def test_refresh_rehydrates_the_enum(session: SnakeSession) -> None:
    """`refresh` reloads columns: the enum has to come back as a MEMBER, not as text."""
    garment = session.add(Prenda(id=1, color=Color.ROJO, talla=Talla.S))
    session.commit()

    session._driver.execute("UPDATE combo_prendas SET color = 'azul' WHERE id = 1", ())  # noqa: SLF001
    session.commit()

    session.refresh(garment)
    assert garment.color is Color.AZUL
