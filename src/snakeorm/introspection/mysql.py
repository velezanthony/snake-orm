"""How MySQL/MariaDB's schema is READ (the third engine). Implements the `SnakeIntrospector` Protocol.

Everything comes out of `information_schema`, which MySQL implements and Postgres implements
differently enough to be worth its own file rather than a shared one with branches in it. The two
real differences:

- **There are no named schemas.** In MySQL a "schema" IS a database, so the `schema` argument names
  the database and defaults to the connected one. Postgres's `public` means nothing here, and
  passing it through as a database name would query a database that does not exist.
- **`tinyint(1)` is `bool`.** MySQL has no boolean, so this is the same one-byte integer that
  everything else uses — but it is what the ORM emits for a `bool`, and reading it back as `int`
  would make every boolean column a permanent drift.

NOT BIJECTIVE, and less so here than on Postgres. The ORM stores a `SnakeUtc` as ISO-8601 TEXT on
this engine and a `UUID` as `CHAR(36)`, so reading them back can only ever say `str`: the type was
already gone when it was written. That is what `drift` compares SQL types for — both sides map to
`TEXT` and agree — and what a scaffolded model shows honestly rather than guessing at.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.drivers import SnakeDriver
from snakeorm.introspection.unsupported import (
    SnakeUnsupportedKind,
    warnings_from_rows,
)
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakeFkAction,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakeIntParams,
    SnakeIntSize,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeStrParams,
    SnakeTableInfo,
    SnakeTypeParams,
)

_PYTHON_TYPES: dict[str, type] = {
    # Several SQL types collapse onto one Python type, the same way they do on Postgres.
    "int": int,
    "bigint": int,
    "smallint": int,
    "mediumint": int,
    "tinyint": int,  # `tinyint(1)` is handled apart: that one IS the bool
    "varchar": str,
    "char": str,
    "text": str,
    "tinytext": str,
    "mediumtext": str,
    "longtext": str,
    "decimal": Decimal,
    "double": float,
    "float": float,
    "date": date,
    "datetime": datetime,
    "timestamp": datetime,
    "time": time,
    "blob": bytes,
    "tinyblob": bytes,
    "mediumblob": bytes,
    "longblob": bytes,
    "binary": bytes,
    "varbinary": bytes,
    "json": dict,
}

_INT_SIZES: dict[str, SnakeIntSize] = {
    # So a scaffolded model re-emits the width it read. Without this a legacy `INT` came back with
    # the default `BIGINT` and the generated file widened the column in silence.
    "smallint": SnakeIntSize.SMALLINT,
    "int": SnakeIntSize.INTEGER,
    "bigint": SnakeIntSize.BIGINT,
}

_FK_ACTIONS: dict[str, SnakeFkAction] = {
    "CASCADE": SnakeFkAction.CASCADE,
    "SET NULL": SnakeFkAction.SET_NULL,
    "RESTRICT": SnakeFkAction.RESTRICT,
    "NO ACTION": SnakeFkAction.NO_ACTION,
}

_UNSUPPORTED_QUERY = f"""
SELECT '{SnakeUnsupportedKind.TRIGGER.value}',
       TRIGGER_NAME, EVENT_OBJECT_TABLE, NULL
FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = %s
UNION ALL
SELECT '{SnakeUnsupportedKind.ROUTINE.value}',
       ROUTINE_NAME, NULL, NULL
FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = %s
UNION ALL
SELECT '{SnakeUnsupportedKind.UNREPRESENTABLE_COLUMN.value}',
       TABLE_NAME, COLUMN_NAME, DATA_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = %s AND DATA_TYPE IN ('set', 'enum', 'geometry', 'bit', 'year')
UNION ALL
SELECT '{SnakeUnsupportedKind.CHECK.value}',
       cc.CONSTRAINT_NAME, tc.TABLE_NAME, cc.CHECK_CLAUSE
FROM information_schema.CHECK_CONSTRAINTS cc
JOIN information_schema.TABLE_CONSTRAINTS tc
  ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA
 AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME
WHERE cc.CONSTRAINT_SCHEMA = %s
ORDER BY 1, 2, 3
"""
"""What the graph cannot represent, TAGGED so `scaffold` can WARN instead of dropping it.

Silence here is what makes somebody believe the generated model covers the whole database. `set`
and `enum` are MySQL's own column-level types and have no counterpart in a Python annotation;
`geometry`, `bit` and `year` have no counterpart at all.

The query says WHAT it found and hands over the pieces; the sentence is written once for the three
engines in `introspection.unsupported`. It used to be composed right here, and the wording drifted
away from the other two engines' — including into another language.
"""


class MySQLIntrospector:
    """Reads a MySQL/MariaDB database's schema and returns it as the SAME metadata graph."""

    def __init__(self, driver: SnakeDriver) -> None:
        self._driver = driver

    def _database(self, schema: str) -> str:
        """The database to read. `public` means "the connected one": it is Postgres's word.

        The Protocol carries `schema` because Postgres needs it, and a caller that passes the
        default would otherwise be asking MySQL for a database literally called `public`.
        """
        if schema != DEFAULT_SCHEMA:
            return schema
        rows = self._driver.fetch_all("SELECT DATABASE()", ())
        return str(rows[0][0]) if rows and rows[0][0] is not None else schema

    def tables(self, schema: str = DEFAULT_SCHEMA) -> list[SnakeTableInfo]:
        """Every base table with its columns, PK, uniqueness, indexes, FKs and comments."""
        database = self._database(schema)
        names = [
            str(row[0])
            for row in self._driver.fetch_all(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
                "AND TABLE_NAME <> 'snake_migrations' ORDER BY TABLE_NAME",
                (database,),
            )
        ]
        return [self._table(database, name) for name in names]

    def _table(self, database: str, name: str) -> SnakeTableInfo:
        """Builds the `SnakeTableInfo` of one table."""
        unique_columns = self._unique_columns(database, name)
        columns = [
            self._column(row, unique_columns)
            for row in self._driver.fetch_all(
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, "
                "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
                "COLUMN_COMMENT, EXTRA, COLUMN_TYPE "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (database, name),
            )
        ]
        by_name = {column.name: column for column in columns}
        return SnakeTableInfo(
            name=name,
            columns=tuple(columns),
            primary_key=SnakePrimaryKeyInfo(
                columns=tuple(
                    by_name[column]
                    for column in self._primary_key_columns(database, name)
                    if column in by_name
                )
            ),
            relationships=self._relationships(database, name),
            schema=DEFAULT_SCHEMA,
            db_comment=self._table_comment(database, name),
            indexes=self._indexes(database, name),
        )

    def _column(
        self, row: tuple[object, ...], unique_columns: set[str]
    ) -> SnakeColumnInfo:
        """Translates a row of `information_schema.COLUMNS` into column metadata."""
        name, data_type, nullable = str(row[0]), str(row[1]), str(row[2])
        default, extra, column_type = row[3], str(row[8]), str(row[9])
        max_length = row[4] if isinstance(row[4], int) else None
        precision = row[5] if isinstance(row[5], int) else None
        scale = row[6] if isinstance(row[6], int) else None
        comment = str(row[7]) if row[7] else None

        # `tinyint(1)` is what this engine calls a boolean, and it is what the ORM writes for one.
        # Reading it back as `int` would make every boolean column drift for ever.
        python_type = (
            bool
            if column_type.lower().startswith("tinyint(1)")
            else _PYTHON_TYPES.get(data_type, str)
        )
        return SnakeColumnInfo(
            name=name,
            python_type=python_type,
            nullable=nullable == "YES",
            unique=name in unique_columns,
            attr_name=name,
            # MySQL says it in `EXTRA`, not in the default: the type stays `int`.
            autoincrement="auto_increment" in extra.lower(),
            db_comment=comment,
            # The DEFAULT is an expression (`CURRENT_TIMESTAMP`), never a Python literal.
            server_default_sql=str(default) if default is not None else None,
            type_params=_type_params(
                data_type, python_type, max_length, precision, scale
            ),
        )

    def _primary_key_columns(self, database: str, name: str) -> list[str]:
        """The PK's columns, IN ORDER — which matters for a composite one."""
        rows = self._driver.fetch_all(
            "SELECT COLUMN_NAME FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = 'PRIMARY' "
            "ORDER BY SEQ_IN_INDEX",
            (database, name),
        )
        return [str(row[0]) for row in rows]

    def _unique_columns(self, database: str, name: str) -> set[str]:
        """Columns carrying uniqueness ON THEIR OWN.

        A unique index over two columns is a table-level rule, not a property of either column, so
        it stays out of here and comes back through `_indexes`.
        """
        rows = self._driver.fetch_all(
            "SELECT INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND NON_UNIQUE = 0 "
            "AND INDEX_NAME <> 'PRIMARY'",
            (database, name),
        )
        by_index: dict[str, list[str]] = {}
        for index_name, column in rows:
            by_index.setdefault(str(index_name), []).append(str(column))
        return {columns[0] for columns in by_index.values() if len(columns) == 1}

    def _indexes(self, database: str, name: str) -> tuple[SnakeIndexInfo, ...]:
        """The table's indexes, PK aside (that one is not an index in the graph)."""
        rows = self._driver.fetch_all(
            "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME <> 'PRIMARY' "
            "ORDER BY INDEX_NAME, SEQ_IN_INDEX",
            (database, name),
        )
        grouped: dict[str, tuple[list[str], bool]] = {}
        for index_name, column, non_unique in rows:
            # `NON_UNIQUE` arrives as 0/1 and the driver decides whether that is an int or a string,
            # so it is normalised through `str` before being read as a number.
            unique = str(non_unique) == "0"
            columns, _ = grouped.setdefault(str(index_name), ([], unique))
            columns.append(str(column))
        return tuple(
            SnakeIndexInfo(columns=tuple(columns), name=index_name, unique=unique)
            for index_name, (columns, unique) in sorted(grouped.items())
        )

    def _relationships(
        self, database: str, name: str
    ) -> tuple[SnakeRelationshipInfo, ...]:
        """The outgoing FKs, as to-one relationships pointing at the target table's NAME."""
        rows = self._driver.fetch_all(
            "SELECT k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME, k.COLUMN_NAME, "
            "k.REFERENCED_COLUMN_NAME, r.DELETE_RULE, r.UPDATE_RULE "
            "FROM information_schema.KEY_COLUMN_USAGE k "
            "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
            "  ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
            " AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
            "WHERE k.TABLE_SCHEMA = %s AND k.TABLE_NAME = %s "
            "AND k.REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY k.CONSTRAINT_NAME, k.ORDINAL_POSITION",
            (database, name),
        )
        grouped: dict[str, list[tuple[object, ...]]] = {}
        for row in rows:
            grouped.setdefault(str(row[0]), []).append(row)
        return tuple(
            self._relationship(constraint, group)
            for constraint, group in sorted(grouped.items())
        )

    def _relationship(
        self, constraint: str, rows: list[tuple[object, ...]]
    ) -> SnakeRelationshipInfo:
        """One FK — COMPOSITE included — as a to-one relationship.

        Grouped by constraint name and not one per column: a two-column FK is ONE relationship, and
        splitting it would produce a mirror with two half-relationships that reference nothing.
        """
        target = str(rows[0][1])
        pairs = tuple((str(row[2]), str(row[3])) for row in rows)
        return SnakeRelationshipInfo(
            name=constraint,
            target=target,
            kind=SnakeRelationshipKind.TO_ONE,
            foreign_key=SnakeForeignKeyInfo(
                target=target,
                pairs=pairs,
                on_delete=_FK_ACTIONS.get(str(rows[0][4]), SnakeFkAction.NO_ACTION),
                on_update=_FK_ACTIONS.get(str(rows[0][5]), SnakeFkAction.NO_ACTION),
            ),
            target_table=target,
        )

    def _table_comment(self, database: str, name: str) -> str | None:
        """The table's comment, if it carries one.

        MySQL answers `''` rather than NULL when there is none, and for an InnoDB table it can also
        answer engine chatter like `InnoDB free: ...`, which is not a comment anybody wrote.
        """
        rows = self._driver.fetch_all(
            "SELECT TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (database, name),
        )
        if not rows or not rows[0][0]:
            return None
        comment = str(rows[0][0])
        return None if comment.startswith("InnoDB free") else comment

    def unsupported(self, schema: str = DEFAULT_SCHEMA) -> list[str]:
        """Objects the ORM cannot represent, described so it can WARN (never dropped in silence)."""
        database = self._database(schema)
        rows = self._driver.fetch_all(
            _UNSUPPORTED_QUERY, (database, database, database, database)
        )
        return warnings_from_rows(rows)


def _type_params(
    data_type: str,
    python_type: type,
    max_length: int | None,
    precision: int | None,
    scale: int | None,
) -> SnakeTypeParams | None:
    """The parameters of the family the type really belongs to — one object, chosen deliberately.

    Same reasoning as the Postgres one: firing all the knobs at every column made an `int` come back
    carrying a `max_length` that meant nothing. Choosing forces you to look at the type.

    `bool` is checked FIRST, and it has to be: a `tinyint(1)` is an integer as far as
    `information_schema` is concerned, so it would otherwise come back with an `int_size` and
    scaffold as `snake_int()` over a `SnakeColumn[bool]` — a contradiction the compiler rejects.
    """
    if python_type is bool:
        return None
    if data_type == "decimal" and precision is not None:
        return SnakeDecimalParams(precision, scale)
    if data_type in _INT_SIZES:
        return SnakeIntParams(size=_INT_SIZES[data_type])
    if data_type in ("varchar", "char") and max_length is not None:
        # Only on the bounded types: `TEXT` also reports a length (65535), and re-emitting it would
        # turn a TEXT column into a VARCHAR(65535) that says something the schema never said.
        return SnakeStrParams(max_length=max_length, fixed=data_type == "char")
    return None
