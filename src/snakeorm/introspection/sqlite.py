"""How SQLite's schema is READ (the second engine). It has no `information_schema`: you ask with PRAGMAs.

The translation into `SnakeTableInfo` is the same as on Postgres, so drift and scaffolding work without being touched. It is not bijective: `VARCHAR(50)`/`TEXT`/`CHAR(10)` are the same affinity, reading back does not reproduce the original.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.introspection.unsupported import (
    SnakeUnsupportedKind,
    warnings_from_rows,
)
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)

_UNSUPPORTED_QUERY = f"""
SELECT '{SnakeUnsupportedKind.TRIGGER.value}', name, tbl_name, NULL
  FROM sqlite_master WHERE type = 'trigger'
UNION ALL
SELECT '{SnakeUnsupportedKind.EXPRESSION_INDEX.value}', name, NULL, NULL
  FROM sqlite_master WHERE type = 'index' AND sql LIKE '%(%(%'
ORDER BY 1, 2
"""
"""What is in the database and the graph cannot express, TAGGED but not worded.

Same shape as the other two engines: the query says what it found, and
`introspection.unsupported` writes the one sentence the three share. SQLite has no
`information_schema`, but `sqlite_master` answers both questions in one pass.
"""

_AFFINITIES: dict[str, type] = {
    # SQLite declares types by AFFINITY (substring rules over the DDL text). What the ORM emits is
    # covered here; everything else falls to `str`, which is what the driver will return anyway.
    "INTEGER": int,
    "INT": int,
    "REAL": float,
    "FLOAT": float,
    "DOUBLE": float,
    "NUMERIC": Decimal,
    "DECIMAL": Decimal,
    "BLOB": bytes,
    "TEXT": str,
    "VARCHAR": str,
    "CHAR": str,
    "DATETIME": datetime,
    "BOOLEAN": bool,
}


def _python_type(declared: str) -> type:
    """Translates the type DECLARED in the DDL into Python, by affinity (prefix: SQLite keeps the text as it is).

    Anything unknown falls to `str`, which is what the driver will hand over anyway.
    """
    normalized = declared.upper().split("(")[0].strip()
    return _AFFINITIES.get(normalized, str)


class SQLiteIntrospector:
    """Reads a SQLite database's schema and returns it as the SAME metadata graph."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def tables(self, schema: str = DEFAULT_SCHEMA) -> list[SnakeTableInfo]:
        """Every user table with its columns, PK, uniqueness, indexes and FKs.

        `schema` is accepted because of the Protocol and is IGNORED: SQLite has no named schemas, and the calling code is the same for both engines.
        """
        names = [
            str(row[0])
            for row in self._driver.fetch_all(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                (),
            )
        ]
        return [self._table(name) for name in names]

    def _table(self, name: str) -> SnakeTableInfo:
        """Builds a table's `SnakeTableInfo` out of its PRAGMAs."""
        unique_names = self._unique_columns(name)
        columns: list[SnakeColumnInfo] = []
        pk: list[SnakeColumnInfo] = []
        for _, col, declared, notnull, _default, pk_pos in self._driver.fetch_all(
            f"PRAGMA table_info({self._quote(name)})", ()
        ):
            kind = _python_type(str(declared))
            column = SnakeColumnInfo(
                name=str(col),
                python_type=kind,
                nullable=not int(notnull) and not int(pk_pos),
                unique=str(col) in unique_names,
                # On SQLite the autoincrement is an `INTEGER PRIMARY KEY`: an alias of the ROWID.
                autoincrement=bool(int(pk_pos)) and kind is int,
                attr_name=str(col),
            )
            columns.append(column)
            if int(pk_pos):
                pk.append(column)
        return SnakeTableInfo(
            name=name,
            columns=tuple(columns),
            primary_key=SnakePrimaryKeyInfo(columns=tuple(pk)),
            indexes=self._indexes(name),
            relationships=self._relations(name),
        )

    def _unique_columns(self, table: str) -> set[str]:
        """Columns with a unique index over a SINGLE column (the uniqueness the ORM declares)."""
        unique_names: set[str] = set()
        for _, index, is_unique, *_rest in self._driver.fetch_all(
            f"PRAGMA index_list({self._quote(table)})", ()
        ):
            if not int(is_unique):
                continue
            columns = [
                str(row[2])
                for row in self._driver.fetch_all(
                    f"PRAGMA index_info({self._quote(str(index))})", ()
                )
            ]
            if len(columns) == 1:
                unique_names.add(columns[0])
        return unique_names

    def _indexes(self, table: str) -> tuple[SnakeIndexInfo, ...]:
        """NON-implicit indexes (`origin` == `c`): nobody declared the ones backing a UNIQUE or a PK, and `check` would see them as drift on a schema the ORM has just created."""
        output: list[SnakeIndexInfo] = []
        for _, index, is_unique, source, _partial in self._driver.fetch_all(
            f"PRAGMA index_list({self._quote(table)})", ()
        ):
            if str(source) != "c":
                continue
            columns = tuple(
                str(row[2])
                for row in self._driver.fetch_all(
                    f"PRAGMA index_info({self._quote(str(index))})", ()
                )
            )
            output.append(
                SnakeIndexInfo(
                    columns=columns, name=str(index), unique=bool(int(is_unique))
                )
            )
        return tuple(sorted(output, key=lambda index: index.name or ""))

    def _relations(self, table: str) -> tuple[SnakeRelationshipInfo, ...]:
        """The table's foreign keys, grouped by `id` (a composite FK is several rows)."""
        by_fk: dict[int, list[tuple[str, str, str]]] = {}
        targets: dict[int, str] = {}
        for (
            fk_id,
            _seq,
            target,
            source,
            target_column,
            _upd,
            _del,
            _match,
        ) in self._driver.fetch_all(
            f"PRAGMA foreign_key_list({self._quote(table)})", ()
        ):
            by_fk.setdefault(int(fk_id), []).append(
                (str(source), str(target_column), str(target))
            )
            targets[int(fk_id)] = str(target)

        output: list[SnakeRelationshipInfo] = []
        for fk_id, pairs in sorted(by_fk.items()):
            target = targets[fk_id]
            output.append(
                SnakeRelationshipInfo(
                    name=f"fk_{table}_{fk_id}",
                    target=target,
                    kind=SnakeRelationshipKind.TO_ONE,
                    foreign_key=SnakeForeignKeyInfo(
                        target=target,
                        pairs=tuple(
                            (source, target_column)
                            for source, target_column, _ in pairs
                        ),
                    ),
                )
            )
        return tuple(output)

    def unsupported(self, schema: str = DEFAULT_SCHEMA) -> list[str]:
        """What is in the database and the ORM cannot express (TRIGGERS and views above all), so it can be warned about instead of dropped in silence.

        ONE query, tagged by kind, like the other two engines: it used to be two queries whose
        sentences were written right here, and one of them —the trigger— did not name the table the
        other engines named, while the Postgres wording of the other had drifted into Spanish.
        `tbl_name` was in `sqlite_master` all along; nobody was asking for it.
        """
        rows = self._driver.fetch_all(_UNSUPPORTED_QUERY, ())
        return warnings_from_rows(rows)

    @staticmethod
    def _quote(name: str) -> str:
        """Quotes an identifier for a PRAGMA (it takes no parameters).

        The names come from `sqlite_master`, but they are quoted anyway: a table can be named after a reserved word, and trusting the source is how injections start.
        """
        escaped = name.replace('"', '""')
        return f'"{escaped}"'
