"""DRIFT detection: what the difference is between what the code says and what is in the database."""

from __future__ import annotations

from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects import SnakeDialect
from snakeorm.metadata import SnakeColumnInfo, SnakeTableInfo


def drift(
    code: list[SnakeTableInfo], database: list[SnakeTableInfo], dialect: SnakeDialect
) -> list[str]:
    """Differences between the compiled metadata and the REAL schema, as text (code vs database, not vs history like `makemigrations --check`).

    It only compares what introspection reads reliably (existence of tables/columns, column type, nullability): defaults and constraints would give false positives that turn the tool into noise. Drift is about what YOU DECLARE: a table the ORM does not know about is not drift, it is somebody else's.

    The `dialect` is not decoration and it is not optional. Comparing PYTHON types across this
    boundary compares something only one side has: a `date` on SQLite is written as `TEXT`, and
    reading `TEXT` back can only ever answer `str`. Both sides are right and they never match, so
    drift used to report three differences against a database the ORM had just built out of the
    very model it was comparing — noise from the one tool whose silence is the whole product.

    The SQL type is what both sides genuinely share, so that is what is compared.
    """
    report: list[str] = []
    in_code = {table.name: table for table in code}
    in_database = {table.name: table for table in database}

    for name in sorted(set(in_code) - set(in_database)):
        report.append(f"table '{name}': is in the code and NOT in the database")

    for name in sorted(set(in_code) & set(in_database)):
        report.extend(_column_drift(name, in_code[name], in_database[name], dialect))
    return report


def _sql_type(column: SnakeColumnInfo, dialect: SnakeDialect) -> str:
    """The SQL type this engine writes for the column, or the dialect's refusal to write one.

    The STORAGE type feeds it, not the declared one: a `StrEnum` is stored as TEXT, so going
    through `python_type` would flag every enum column as permanent drift.

    A refusal is returned as text rather than raised: drift is a diagnostic, and a model this
    engine cannot represent is exactly the kind of thing it exists to tell you about — not a
    reason for the report to blow up half-written.
    """
    try:
        return dialect.map_type(column.storage_type, params=column.type_params)
    except SnakeDialectError as refusal:
        return f"<not representable: {refusal}>"


def _column_drift(
    table: str, code: SnakeTableInfo, database: SnakeTableInfo, dialect: SnakeDialect
) -> list[str]:
    """Column differences for a table present on both sides."""
    report: list[str] = []
    in_code = {column.name: column for column in code.columns}
    in_database = {column.name: column for column in database.columns}

    for name in sorted(set(in_code) - set(in_database)):
        report.append(f"{table}.{name}: is in the code and NOT in the database")
    for name in sorted(set(in_database) - set(in_code)):
        report.append(f"{table}.{name}: is in the database and NOT in the code")

    for name in sorted(set(in_code) & set(in_database)):
        expected, actual = in_code[name], in_database[name]
        written, found = _sql_type(expected, dialect), _sql_type(actual, dialect)
        if written != found:
            report.append(
                f"{table}.{name}: the code stores {written} and the database has {found}"
            )
        if expected.nullable != actual.nullable:
            state = "accepts NULL" if actual.nullable else "does NOT accept NULL"
            report.append(
                f"{table}.{name}: the database {state} and the code says the opposite"
            )
    return report
