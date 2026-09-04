"""The three engines WORD an `unsupported` finding the same way, because ONE catalogue words it.

`scaffold` never drops what the graph cannot represent: it WARNS, and `cli/app.py` writes those very
sentences as comments inside the `models.py` the user commits into their own repository. The sentence
is the product, so there has to be exactly one of it.

There were three. Postgres composed its warnings inside its own SQL and composed them IN SPANISH
(`índice por expresión: `, `columna de tipo no representable: `) while MySQL said `column of a type
with no equivalent: ` for the same finding; and where those two said `trigger: {name} on {table}`,
SQLite said `trigger not representable in the model: {name}` and did not name the table at all.
Three engines, three redactions of the same complaint, and nothing compared them because each one
lived buried in a different query.

What is checked here is the sentence each engine RETURNS for the same finding, with no database
involved: the engines tag the row with a kind and `introspection.unsupported` writes the sentence.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.introspection import (
    MySQLIntrospector,
    PostgresIntrospector,
    SnakeIntrospector,
    SQLiteIntrospector,
)
from snakeorm.introspection.unsupported import SnakeUnsupportedKind

_SCHEMA = "shop"
"""A schema that is NOT the default, so MySQL does not go asking the driver which database it is on."""


class _CannedDriver:
    """Driver double that answers EVERY query with the same catalogue rows.

    The query is deliberately ignored: each engine asks its own catalogue (`pg_catalog`,
    `information_schema`, `sqlite_master`) and that difference is legitimate and permanent. What may
    not differ is the sentence the three build out of the answer.
    """

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return list(self.rows)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

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


def _warnings_of(
    introspector: type[PostgresIntrospector]
    | type[MySQLIntrospector]
    | type[SQLiteIntrospector],
    rows: list[tuple[object, ...]],
) -> list[str]:
    """The warnings one engine returns for the given catalogue rows."""
    reader: SnakeIntrospector = introspector(_CannedDriver(rows))
    return reader.unsupported(_SCHEMA)


_ENGINES = [PostgresIntrospector, MySQLIntrospector, SQLiteIntrospector]


@pytest.mark.parametrize("introspector", _ENGINES, ids=lambda item: item.__name__)
def test_a_trigger_is_worded_the_same_by_every_engine(
    introspector: type[PostgresIntrospector]
    | type[MySQLIntrospector]
    | type[SQLiteIntrospector],
) -> None:
    """The same trigger produces the SAME sentence on Postgres, MySQL and SQLite.

    Each engine is compared against ONE expected string rather than against its own former wording,
    which is what makes this a comparison of the three and not three separate pins.
    """
    rows: list[tuple[object, ...]] = [
        (SnakeUnsupportedKind.TRIGGER.value, "touch_invoice", "invoices", None)
    ]

    assert _warnings_of(introspector, rows) == ["trigger: touch_invoice on invoices"]


@pytest.mark.parametrize("introspector", _ENGINES, ids=lambda item: item.__name__)
def test_a_check_is_worded_the_same_by_every_engine(
    introspector: type[PostgresIntrospector]
    | type[MySQLIntrospector]
    | type[SQLiteIntrospector],
) -> None:
    """A CHECK constraint reads the same on the three, and it QUOTES the server's expression.

    `snake_check` takes a `SnakeCondition`, never a string, so the mirror has no way to declare
    one: reconstructing the condition from the server's text would be writing a SQL parser. The
    rule is still there and still rejecting rows, so the expression travels verbatim — it is the
    only thing that tells the reader what the database is enforcing behind their model.
    """
    rows: list[tuple[object, ...]] = [
        (SnakeUnsupportedKind.CHECK.value, "ck_invoices_total", "invoices", "total > 0")
    ]

    assert _warnings_of(introspector, rows) == [
        "check: ck_invoices_total on invoices (total > 0)"
    ]


@pytest.mark.parametrize("introspector", _ENGINES, ids=lambda item: item.__name__)
def test_an_expression_index_is_worded_the_same_by_every_engine(
    introspector: type[PostgresIntrospector]
    | type[MySQLIntrospector]
    | type[SQLiteIntrospector],
) -> None:
    """An index over an expression says the same thing whichever engine found it.

    This is the one that was in Spanish on Postgres (`índice por expresión: `) and in English on
    SQLite, and the difference reached the generated `models.py`.
    """
    rows: list[tuple[object, ...]] = [
        (SnakeUnsupportedKind.EXPRESSION_INDEX.value, "ix_lower_email", None, None)
    ]

    assert _warnings_of(introspector, rows) == ["expression index: ix_lower_email"]


@pytest.mark.parametrize("introspector", _ENGINES, ids=lambda item: item.__name__)
def test_a_column_with_no_equivalent_is_worded_the_same_by_every_engine(
    introspector: type[PostgresIntrospector]
    | type[MySQLIntrospector]
    | type[SQLiteIntrospector],
) -> None:
    """A column whose SQL type has no Python equivalent reads the same on the three engines.

    Postgres said `columna de tipo no representable: ` and MySQL `column of a type with no
    equivalent: ` about the very same situation.
    """
    rows: list[tuple[object, ...]] = [
        (
            SnakeUnsupportedKind.UNREPRESENTABLE_COLUMN.value,
            "places",
            "area",
            "geometry",
        )
    ]

    assert _warnings_of(introspector, rows) == [
        "column of a type with no equivalent: places.area (geometry)"
    ]


@pytest.mark.parametrize("introspector", _ENGINES, ids=lambda item: item.__name__)
def test_a_routine_is_worded_the_same_by_every_engine(
    introspector: type[PostgresIntrospector]
    | type[MySQLIntrospector]
    | type[SQLiteIntrospector],
) -> None:
    """A stored routine reads the same whichever engine reported it.

    Only MySQL looks for routines today. That is a difference in what each catalogue is ASKED, which
    is legitimate; the wording is not allowed to be a second difference on top.
    """
    rows: list[tuple[object, ...]] = [
        (SnakeUnsupportedKind.ROUTINE.value, "recalc_totals", None, None)
    ]

    assert _warnings_of(introspector, rows) == ["routine: recalc_totals"]


def test_a_kind_nobody_words_blows_up_instead_of_being_skipped() -> None:
    """A catalogue row with an unknown kind FAILS instead of vanishing.

    Skipping it would be the exact silence this whole module exists to prevent: the engine bothered
    to report the object, and dropping it makes the mirror look complete when it is not.
    """
    with pytest.raises(ValueError, match="materialised_view"):
        _warnings_of(PostgresIntrospector, [("materialised_view", "sales", None, None)])
