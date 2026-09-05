"""Drift detection: what difference there is between what the code says and what is in the DB.

It comes almost for free out of the introspection because both sides are the SAME graph: no
translator is needed to compare them.

And it is NOT the same as `makemigrations --check`. That one compares the code against the HISTORY
and answers "am I missing a migration to generate?". This compares the code against the real
database and answers "did somebody touch it from outside?". Confusing them leaves a hole through
which slips precisely the change nobody recorded.
"""

from __future__ import annotations

from enum import StrEnum

from snakeorm.dialects import PostgresDialect
from snakeorm.introspection import drift
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)

_ID = SnakeColumnInfo(name="id", python_type=int)


class _State(StrEnum):
    """Text enum for the enumerated column case."""

    ALTA = "alta"
    BAJA = "baja"


_DIALECT = PostgresDialect()


def _table(name: str, *columns: SnakeColumnInfo) -> SnakeTableInfo:
    """Table with the PK and the given columns."""
    return SnakeTableInfo(
        name=name,
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


def test_no_drift_when_both_sides_agree() -> None:
    """Checks the good case: no differences, empty report (and exit code 0 in the CLI)."""
    code = [_table("users", SnakeColumnInfo(name="email", python_type=str))]
    real = [_table("users", SnakeColumnInfo(name="email", python_type=str))]
    assert drift(code, real, _DIALECT) == []


def test_a_table_missing_in_the_database_is_reported() -> None:
    """Checks that a table in the code that does not exist is flagged (a migration is missing)."""
    report = drift([_table("users"), _table("orders")], [_table("users")], _DIALECT)
    assert report == ["table 'orders': is in the code and NOT in the database"]


def test_a_table_the_code_never_declared_is_left_alone() -> None:
    """Checks that a foreign table is NOT drift: the code did not declare it, it has no opinion on it.

    Drift measures one single thing: whether what THIS code declares matches what is there. A table
    nobody declared here may belong to another application on the same database, to a
    `@snake_db_first` mirror or to an external tool, and none of the three is a problem. Flagging
    them filled the report with noise, and a noisy report stops being read — which is exactly when
    the real drift slips through.
    """
    report = drift([_table("users")], [_table("users"), _table("legacy")], _DIALECT)
    assert report == []


def test_a_column_added_by_hand_is_reported() -> None:
    """THE REAL CASE: somebody added a column with an ALTER TABLE and nobody recorded it."""
    code = [_table("users")]
    real = [_table("users", SnakeColumnInfo(name="hotfix", python_type=str))]

    assert drift(code, real, _DIALECT) == [
        "users.hotfix: is in the database and NOT in the code"
    ]


def test_a_changed_type_is_reported() -> None:
    """Checks that a different type comes out, with BOTH sides in the message."""
    code = [_table("users", SnakeColumnInfo(name="age", python_type=int))]
    real = [_table("users", SnakeColumnInfo(name="age", python_type=str))]

    assert drift(code, real, _DIALECT) == [
        "users.age: the code stores BIGINT and the database has TEXT"
    ]


def test_an_enum_column_is_not_drift() -> None:
    """Checks that an enum is NOT drift: it is stored as a plain string on purpose, not by mistake.

    The introspector can only return what the database knows, and the database knows nothing of
    enums: it sees a sized string. Comparing against the DECLARED type marked every enumerated column
    as permanent drift, with nothing the user could do to silence it. What is compared is the STORAGE
    type, which is the only one both sides can know — and the WIDTH is part of that type, because
    the metadata derives it from the enum's longest member.
    """
    code = [
        _table(
            "users",
            SnakeColumnInfo(name="estado", python_type=_State, enum_type=_State),
        )
    ]
    real = [
        _table(
            "users",
            SnakeColumnInfo(
                name="estado", python_type=str, type_params=SnakeStrParams(max_length=4)
            ),
        )
    ]

    assert drift(code, real, _DIALECT) == []


def test_an_enum_column_left_unsized_by_an_older_schema_IS_drift() -> None:
    """A database created before the enum's width was derived really has drifted, and it is said so.

    This is the honest half of the change and it costs something, so it is written down rather than
    discovered. A schema created back when an enum column came out `TEXT` no longer matches a model
    that now says `VARCHAR(n)`, and drift reports it — correctly: the two really are different types.

    What makes it sharp is that `makemigrations` will NOT propose the fix. The autogen compares the
    model against the migration FILES replayed, and a generated file spells an enum column with
    `enum_type=` and no `type_params`, so the replayed side derives the very same width the model
    does and the two converge. Only the DATABASE is behind, which is exactly the case drift exists
    for — and exactly the case its report has to be trusted on, because nothing else will say it.
    """
    code = [
        _table(
            "users",
            SnakeColumnInfo(name="estado", python_type=_State, enum_type=_State),
        )
    ]
    real = [_table("users", SnakeColumnInfo(name="estado", python_type=str))]

    assert drift(code, real, _DIALECT) == [
        "users.estado: the code stores VARCHAR(4) and the database has TEXT"
    ]


def test_a_changed_nullability_is_reported() -> None:
    """Checks that nullability is watched too: it is the one that breaks inserts in production."""
    code = [_table("users", SnakeColumnInfo(name="email", python_type=str))]
    real = [
        _table("users", SnakeColumnInfo(name="email", python_type=str, nullable=True))
    ]

    report = drift(code, real, _DIALECT)
    assert report == [
        "users.email: the database accepts NULL and the code says the opposite"
    ]


def test_several_differences_come_out_together() -> None:
    """Checks that the report does not stop at the first one: fixing them one by one is torture."""
    code = [
        _table("users", SnakeColumnInfo(name="email", python_type=str)),
        _table("orders"),
    ]
    real = [_table("users", SnakeColumnInfo(name="email", python_type=int))]

    assert len(drift(code, real, _DIALECT)) == 2


def test_a_schema_the_orm_itself_created_shows_no_drift_on_sqlite() -> None:
    """Reading back what the ORM just wrote reports NOTHING. Anything else is noise, not drift.

    Drift exists to say "the code and the database disagree". Run against SQLite it disagreed with
    a database it had built itself, out of the very model being compared: a `date` column, a `bool`
    and a `Decimal` came back as three differences. Three lines of alarm about nothing, on the tool
    whose only value is that its silence means something.

    The cause is a comparison made in the wrong currency. `storage_type` describes itself as "the
    Python type the DIALECT maps to SQL" and knows no dialect, so it answers `date` on both sides of
    an engine that cannot store a date: SQLite writes `TEXT`, and reading `TEXT` back can only ever
    say `str`. Both answers are right and they will never match.

    The two sides DO share one thing, and it is the SQL type. `date` and `str` both map to `TEXT`
    here, so they agree — while a genuine mismatch, `int` against `str`, is still `BIGINT` against
    `TEXT` and still gets reported.

    Note what the fix is NOT. Making the dialect emit `DATE`/`BOOLEAN`/`DECIMAL` so the names
    survive is the obvious move and it is a trap: in SQLite `DECIMAL` carries NUMERIC affinity, so
    `'9.99'` is stored as a `real` — measured — and the exact-decimal guarantee dies to make an
    introspector tidier. `TEXT` is the correct emission and the comparison is what was wrong.
    """
    from snakeorm import SQLiteDialect, SQLiteDriver
    from snakeorm.introspection.sqlite import SQLiteIntrospector
    from snakeorm.migration import emit_create_table

    dialect = SQLiteDialect()
    declared = _table_with_every_awkward_type()
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(declared, dialect), ())
    driver.commit()
    read_back = next(
        table
        for table in SQLiteIntrospector(driver).tables()
        if table.name == declared.name
    )

    assert drift([declared], [read_back], dialect) == [], (
        "the ORM wrote this schema from this model; there is nothing for drift to report"
    )


def test_a_real_mismatch_is_still_reported(dialect_free: None = None) -> None:
    """The quieter comparison did not go deaf: a column typed `int` in code and `str` in the
    database is still two different SQL types, and still drift."""
    from snakeorm import SQLiteDialect

    code = _table("users", SnakeColumnInfo(name="edad", python_type=int))
    real = _table("users", SnakeColumnInfo(name="edad", python_type=str))

    assert drift([code], [real], SQLiteDialect()) == [
        "users.edad: the code stores INTEGER and the database has TEXT"
    ]


def _table_with_every_awkward_type() -> SnakeTableInfo:
    """A table whose types SQLite cannot keep: date, bool and Decimal all collapse on the way in."""
    from datetime import date
    from decimal import Decimal

    identifier = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="drift_probe",
        columns=(
            identifier,
            SnakeColumnInfo(name="cuando", python_type=date),
            SnakeColumnInfo(name="activo", python_type=bool),
            SnakeColumnInfo(name="importe", python_type=Decimal),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(identifier,)),
    )
