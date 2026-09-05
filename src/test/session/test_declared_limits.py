"""Tests that a DECLARED LIMIT is enforced in Python, not delegated to the engine.

Declaring `snake_str(max_length=5)` or `snake_int(size=SMALLINT)` is a domain rule. If the ORM only
writes it into the DDL and lets the engine enforce it, the rule is worth something different
depending on where you run: Postgres REJECTS (`value too long for type character varying(5)`,
`smallint out of range`) and SQLite ACCEPTS, because it ignores the VARCHAR length and collapses
every integer into INTEGER.

That turns the SQLite dialect —which exists so that you can work without a server— into a trap: you
develop and test on SQLite with the suite green, you deploy on Postgres and it blows up.

The project already chose the answer for one of the knobs. The docstring of `_guard_decimal_scale`
says so: *"Without this the scale was only enforced by Postgres (rounding silently) while SQLite
ignored it; failing here makes it hold on BOTH engines"*. These tests extend that decision to the
ones that were missing, and carry it to the bulk write path, which was skipping it.

It SHOUTS, it does not truncate: trimming the text or the number on the inside would be converting
behind the developer's back, and this ORM does not do that.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SQLiteDialect,
    snake_column,
    snake_decimal,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeValueError
from snakeorm.metadata import SnakeIntSize


@snake_model(table="limites_declarados")
class Limitado(SnakeModel):
    """Model with one knob from each family that DOES impose a limit."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    codigo: SnakeColumn[str] = snake_str(max_length=5)
    quantity: SnakeColumn[int] = snake_int(size=SnakeIntSize.SMALLINT)
    amount: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)


class _Driver:
    """Driver that runs nothing: the guard must fire BEFORE anything reaches the database.

    That is the whole point of these tests. If the check lived in the engine, nothing would fire
    here — and that is exactly what happens on SQLite today.
    """

    def fetch_all(self, sql: str, params: object) -> list[tuple[object, ...]]:
        # Empty: with no RETURNING rows nothing gets copied back into the instance. Hydration is
        # not what is tested here, and returning a fixed row would force it to line up with the
        # columns of every model in the file.
        return []

    def fetch_iter(self, sql: str, params: object, *, chunk: int = 1000):  # type: ignore[no-untyped-def]
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: object) -> int:
        return 1

    @property
    def last_insert_id(self) -> int:
        return 1

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


@pytest.fixture
def session() -> SnakeSession:
    """Session over a mute driver: what is tested is the guard, not the engine."""
    return SnakeSession(_Driver(), SQLiteDialect())


def _valido(**cambios: object) -> Limitado:
    """An instance within every limit, with whichever fields are asked for replaced."""
    fields: dict[str, object] = {
        "id": 1,
        "codigo": "ABC",
        "quantity": 10,
        "amount": Decimal("1.00"),
    }
    fields.update(cambios)
    return Limitado(**fields)  # type: ignore[arg-type]


def test_a_value_within_every_limit_is_accepted(session: SnakeSession) -> None:
    """Verifies that the guard does not get in the way of what is legal (closing too much is bad)."""
    session.add(_valido())


def test_text_longer_than_max_length_is_rejected(session: SnakeSession) -> None:
    """Verifies that text longer than `max_length` is rejected ON WRITING.

    On Postgres this would be `value too long for type character varying(5)`; on SQLite it would go
    in as-is, because SQLite ignores the VARCHAR length. The guard levels the two engines.
    """
    with pytest.raises(SnakeValueError, match="max_length"):
        session.add(_valido(codigo="DEMASIADO LARGO"))


def test_text_exactly_at_max_length_is_accepted(session: SnakeSession) -> None:
    """Verifies that the limit is INCLUSIVE: `max_length=5` admits five characters."""
    session.add(_valido(codigo="ABCDE"))


def test_an_integer_out_of_its_declared_width_is_rejected(
    session: SnakeSession,
) -> None:
    """Verifies that an integer outside the range of its width is rejected ON WRITING.

    `SMALLINT` is 16 signed bits. Postgres would answer `smallint out of range`; SQLite would accept
    it, because it collapses every integer into its 64-bit INTEGER.
    """
    with pytest.raises(SnakeValueError, match="SMALLINT"):
        session.add(_valido(quantity=99_999_999))


def test_a_negative_integer_out_of_range_is_rejected(session: SnakeSession) -> None:
    """Verifies that the range is checked from BOTH sides, not only from above."""
    with pytest.raises(SnakeValueError, match="SMALLINT"):
        session.add(_valido(quantity=-99_999_999))


def test_the_edges_of_the_declared_width_are_accepted(session: SnakeSession) -> None:
    """Verifies that the exact edges of `SMALLINT` (±32,767 / −32,768) go in."""
    session.add(_valido(quantity=32_767))
    session.add(_valido(quantity=-32_768))


def test_more_decimals_than_the_declared_scale_is_rejected(
    session: SnakeSession,
) -> None:
    """Verifies that the `scale` guard that already existed still stands after generalising it."""
    with pytest.raises(SnakeValueError, match="scale"):
        session.add(_valido(amount=Decimal("1.23456")))


def test_a_bool_column_is_not_range_checked_as_an_integer(
    session: SnakeSession,
) -> None:
    """Verifies that a `bool` column does not go through the integer range check.

    In Python `bool` IS a subclass of `int`, so a careless `isinstance(value, int)` would treat
    `True` as an integer and measure the width of a column that is not an integer one. The dispatch
    has to go by the DECLARED TYPE of the column, not by whatever the value turns out to be.
    """

    @snake_model(table="limites_bool")
    class ConBool(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        active: SnakeColumn[bool] = snake_column()

    session.add(ConBool(id=1, active=True))


def test_update_also_enforces_the_limits(session: SnakeSession) -> None:
    """Verifies that `update()` checks just like `add()`: writing is writing."""
    row = _valido()
    row.codigo = "DEMASIADO LARGO"
    with pytest.raises(SnakeValueError, match="max_length"):
        session.update(row)


def test_bulk_update_also_enforces_the_limits(session: SnakeSession) -> None:
    """Verifies that `update_where()` checks too, which was the path that got away.

    It is the most dangerous hole of the three: a bulk write is exactly where an out-of-limit value
    does the most damage, and it was the only write path with no guard.
    """
    query = SnakeQuery(Limitado).filter(Limitado.id == 1)
    with pytest.raises(SnakeValueError, match="max_length"):
        session.update_where(query, [(Limitado.codigo, "DEMASIADO LARGO")])


def test_bulk_update_enforces_the_integer_width(session: SnakeSession) -> None:
    """Verifies that the bulk write checks the integer width as well."""
    query = SnakeQuery(Limitado).filter(Limitado.id == 1)
    with pytest.raises(SnakeValueError, match="SMALLINT"):
        session.update_where(query, [(Limitado.quantity, 99_999_999)])


def test_bulk_update_enforces_the_decimal_scale(session: SnakeSession) -> None:
    """Verifies that the bulk write checks the scale of the NUMERIC as well."""
    query = SnakeQuery(Limitado).filter(Limitado.id == 1)
    with pytest.raises(SnakeValueError, match="scale"):
        session.update_where(query, [(Limitado.amount, Decimal("1.23456"))])


def test_bulk_update_leaves_expressions_alone(session: SnakeSession) -> None:
    """Verifies that a value which is an EXPRESSION (`views + 1`) is not checked at all.

    Its value is computed by the server, so there is nothing here to measure. Trying would give a
    false error in the one case where the check is impossible by definition.
    """
    query = SnakeQuery(Limitado).filter(Limitado.id == 1)
    session.update_where(query, [(Limitado.quantity, Limitado.quantity + 1)])


def test_none_passes_the_guard(session: SnakeSession) -> None:
    """Verifies that a NULL is not measured: nullability is decided by the annotation, not here."""

    @snake_model(table="limites_nulos")
    class Nulo(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        codigo: SnakeColumn[str | None] = snake_str(max_length=5)

    session.add(Nulo(id=1, codigo=None))
