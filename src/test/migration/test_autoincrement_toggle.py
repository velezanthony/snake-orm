"""Tests of the `int` <-> autoincrement toggle: the SQL EMITTED, not just the diff.

There were tests of the diff and none of the `up_sql`, and that is exactly where the bug lived.
Postgres emitted `ALTER COLUMN "code" TYPE BIGSERIAL USING "code"::BIGSERIAL`, and `BIGSERIAL` is
not a Postgres type: it is a `CREATE TABLE` shorthand for BIGINT + a SEQUENCE + a `DEFAULT
nextval(...)`. The server answers `type "bigserial" does not exist`.

The reverse direction was worse because it did NOT fail: `TYPE BIGINT USING "code"::BIGINT` on a
column that is already `bigint` is a no-op that leaves the `DEFAULT nextval(...)` and the sequence
in place. A green migration that changed nothing.

The shorthand is therefore expanded into what it MEANS. MySQL needs none of this (`MODIFY COLUMN`
carries `AUTO_INCREMENT` in the definition and works both ways) and SQLite never gets here, because
`Cap.ALTER_COLUMN` stops the plan first.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import PsycopgDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIntParams,
    SnakeIntSize,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AlterColumn,
    diff_schema,
    emit_alter_column,
    emit_create_table,
    realize,
)
from test.conftest import NO_SERVER_REASON
from test.scenarios.db import dsn

_POSTGRES = PostgresDialect()
_SEQUENCE = '"public"."ai_probe_code_seq"'
_TABLE = '"public"."ai_probe"'


def _column(
    *, autoincrement: bool, size: SnakeIntSize | None = None
) -> SnakeColumnInfo:
    """The `code` column, autoincrementing or plain, optionally with an int width."""
    return SnakeColumnInfo(
        name="code",
        python_type=int,
        autoincrement=autoincrement,
        type_params=None if size is None else SnakeIntParams(size=size),
    )


def _table(column: SnakeColumnInfo) -> SnakeTableInfo:
    """The `ai_probe` table with its `id` plus the `code` column in whatever state it is handed."""
    id_column = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="ai_probe",
        columns=(id_column, column),
        primary_key=SnakePrimaryKeyInfo(columns=(id_column,)),
    )


def test_the_diff_still_sees_the_toggle() -> None:
    """Verifies the diff produces an AlterColumn for the toggle (it is not in _NOT_A_COLUMN_CHANGE)."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    operations = diff_schema([_table(plain)], [_table(auto)])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)
    assert operations[0].new.autoincrement is True


def test_postgres_never_writes_the_create_table_shorthand_in_an_alter() -> None:
    """Verifies no SERIAL shorthand reaches an ALTER, in either direction and at any int width."""
    for size in (SnakeIntSize.SMALLINT, SnakeIntSize.INTEGER, SnakeIntSize.BIGINT):
        plain = _column(autoincrement=False, size=size)
        auto = _column(autoincrement=True, size=size)
        for old, new in ((plain, auto), (auto, plain)):
            for statement in emit_alter_column(_table(new), old, new, _POSTGRES):
                assert "SERIAL" not in statement.upper()


def test_postgres_expands_the_shorthand_into_its_sequence() -> None:
    """Verifies `int` -> autoincrement emits the sequence, the default and the setval."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    assert emit_alter_column(_table(auto), plain, auto, _POSTGRES) == [
        f"CREATE SEQUENCE {_SEQUENCE}",
        f'ALTER TABLE {_TABLE} ALTER COLUMN "code" SET DEFAULT '
        f"nextval('{_SEQUENCE}'::regclass)",
        f'ALTER SEQUENCE {_SEQUENCE} OWNED BY {_TABLE}."code"',
        f"SELECT setval('{_SEQUENCE}', "
        f'COALESCE((SELECT MAX("code") FROM {_TABLE}), 0) + 1, false)',
    ]


def test_postgres_setval_is_what_keeps_the_keys_from_repeating() -> None:
    """Verifies the sequence is positioned at the current MAX, not left at 1 over a populated table."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    statements = emit_alter_column(_table(auto), plain, auto, _POSTGRES)
    setval = [statement for statement in statements if "setval" in statement]
    assert len(setval) == 1
    assert 'MAX("code")' in setval[0]
    # `is_called=false` means the NEXT nextval() returns exactly this value, so an empty table
    # (MAX is NULL -> COALESCE 0) starts at 1, like a freshly created BIGSERIAL.
    assert setval[0].endswith("+ 1, false)")


def test_postgres_widens_the_column_when_the_serial_family_changes_width() -> None:
    """Verifies an INTEGER -> BIGSERIAL toggle still changes the underlying type, as BIGINT."""
    plain = _column(autoincrement=False, size=SnakeIntSize.INTEGER)
    auto = _column(autoincrement=True, size=SnakeIntSize.BIGINT)
    statements = emit_alter_column(_table(auto), plain, auto, _POSTGRES)
    assert (
        f'ALTER TABLE {_TABLE} ALTER COLUMN "code" TYPE BIGINT USING "code"::BIGINT'
        in statements
    )


def test_postgres_drops_the_default_and_the_sequence_on_the_way_back() -> None:
    """Verifies autoincrement -> `int` really undoes it instead of emitting a silent no-op."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    assert emit_alter_column(_table(plain), auto, plain, _POSTGRES) == [
        f'ALTER TABLE {_TABLE} ALTER COLUMN "code" DROP DEFAULT',
        f"DROP SEQUENCE {_SEQUENCE}",
    ]


def test_the_operation_round_trips_through_up_and_down() -> None:
    """Verifies `AlterColumn.down_sql` is the exact reverse of its `up_sql`."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    operation = AlterColumn(_table(auto), plain, auto)
    assert operation.up_sql(_POSTGRES) == emit_alter_column(
        _table(auto), plain, auto, _POSTGRES
    )
    assert operation.down_sql(_POSTGRES) == emit_alter_column(
        _table(plain), auto, plain, _POSTGRES
    )


def test_mysql_keeps_carrying_it_in_the_definition() -> None:
    """Verifies MySQL is untouched: MODIFY COLUMN spells the toggle in one statement, both ways."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    dialect = MySQLDialect()
    assert emit_alter_column(_table(auto), plain, auto, dialect) == [
        "ALTER TABLE `ai_probe` MODIFY COLUMN `code` BIGINT AUTO_INCREMENT"
    ]
    assert emit_alter_column(_table(plain), auto, plain, dialect) == [
        "ALTER TABLE `ai_probe` MODIFY COLUMN `code` BIGINT NOT NULL"
    ]


def test_sqlite_stops_in_the_plan_and_says_so() -> None:
    """Verifies SQLite never reaches the emitter: `Cap.ALTER_COLUMN` stops the plan with a reason."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)
    with pytest.raises(SnakeMigrationError, match="alter an existing column"):
        realize([AlterColumn(_table(auto), plain, auto)], SQLiteDialect())


# --- Applied against a real server, which is the only place `BIGSERIAL` ever showed up ---


@pytest.fixture
def driver() -> Iterator[PsycopgDriver]:
    """Real Postgres driver with the probe table clean before and after."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    connection.execute("DROP TABLE IF EXISTS ai_probe CASCADE", ())
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute("DROP TABLE IF EXISTS ai_probe CASCADE", ())
        connection.commit()
        connection.close()


@pytest.mark.integration
def test_the_toggle_applies_and_reverts_on_a_real_postgres(
    driver: PsycopgDriver,
) -> None:
    """Verifies the whole cycle on the server: create, up, catalogue, insert, down, catalogue."""
    plain, auto = _column(autoincrement=False), _column(autoincrement=True)

    def run(statements: list[str]) -> None:
        """Applies the statements and commits, as the runner would."""
        for statement in statements:
            driver.execute(statement, ())
        driver.commit()

    def column_default() -> str | None:
        """The `code` column's DEFAULT, read from the catalogue."""
        rows = driver.fetch_all(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'ai_probe' AND column_name = 'code'",
            (),
        )
        return None if rows[0][0] is None else str(rows[0][0])

    def sequence_exists() -> bool:
        """Whether the sequence the toggle owns is in the catalogue."""
        rows = driver.fetch_all("SELECT to_regclass('public.ai_probe_code_seq')", ())
        return rows[0][0] is not None

    run([emit_create_table(_table(plain), _POSTGRES)])
    run(["INSERT INTO ai_probe (id, code) VALUES (1, 10), (2, 42)"])

    operation = AlterColumn(_table(auto), plain, auto)
    run(operation.up_sql(_POSTGRES))
    assert column_default() == "nextval('ai_probe_code_seq'::regclass)"
    assert sequence_exists()

    # The setval is what makes this safe on a populated table: the next key is MAX + 1, not 1.
    rows = driver.fetch_all("INSERT INTO ai_probe (id) VALUES (3) RETURNING code", ())
    assert rows[0][0] == 43
    driver.commit()

    run(operation.down_sql(_POSTGRES))
    assert column_default() is None
    assert not sequence_exists()
