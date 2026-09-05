"""Index advisor: spots FILTER/FK columns with no index, from the SCHEMA (static) or from the
QUERIES actually emitted (dynamic). Cross-checking against the metadata avoids suggesting what is
already indexed (PK, unique or a declared index). FKs are the most filtered and joined columns of
all; without an index, correlated aggregates at scale crawl (a 64 s annotate that drops to 41 ms
with one).

- `unindexed_foreign_keys(tables)` -> STATIC audit of the schema (used by `snakeorm advise`).
- `index_hints_from_sql(sqls, tables)` -> pulls unindexed filter columns out of some SQL.
- `index_hints_from_records(rows, tables, min_ms=...)` -> for SLOW queries ONLY (used by the panel):
  a fast query over an unindexed column does not deserve an index; a slow one does. Every suggestion
  carries the WORST duration that triggered it, so they can be ordered and the advice justified.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from snakeorm.metadata import SnakeTableInfo
from snakeorm.metadata.relationship_kind import SnakeRelationshipKind

# Default threshold: below this a query is so fast that an index changes nothing.
DEFAULT_MIN_MS = 10.0

# The ORM's correlated subquery: `FROM "table" AS eN WHERE eN."col" = ...`.
_CORRELATED = re.compile(r'FROM "(\w+)" AS \w+\s+WHERE \w+\."(\w+)"')
# A plain WHERE over the FROM's table: `FROM "table" [AS x] WHERE ("col"` or `WHERE "col"`.
_SIMPLE_WHERE = re.compile(r'FROM "(\w+)"(?: AS \w+)? WHERE \(?"(\w+)"')


def _indexed_columns(table: SnakeTableInfo) -> set[str]:
    """Columns of `table` that ALREADY have an index: PK, `unique=True` and declared indexes."""
    names = {column.name for column in table.primary_key.columns}
    names |= {column.name for column in table.columns if column.unique}
    for index in table.indexes:
        names.update(index.columns)
    return names


def unindexed_foreign_keys(tables: Iterable[SnakeTableInfo]) -> list[tuple[str, str]]:
    """`(table, column)` for every FK with NO index, deduplicated, in order of appearance."""
    hints: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for table in tables:
        indexed = _indexed_columns(table)
        for relationship in table.relationships:
            if relationship.kind is not SnakeRelationshipKind.TO_ONE:
                continue  # only the side that OWNS the FK (to-one) has local columns
            for local, _remote in relationship.foreign_key.pairs:
                key = (table.name, local)
                if local not in indexed and key not in seen:
                    seen.add(key)
                    hints.append(key)
    return hints


def index_hints_from_sql(
    sqls: Iterable[str], tables: Iterable[SnakeTableInfo]
) -> list[tuple[str, str]]:
    """`(table, column)` for columns FILTERED in `sqls` that are NOT indexed, deduplicated.

    Parses the emitted SQL (correlated subqueries and plain WHEREs) and cross-checks the metadata.
    Only suggests columns that EXIST in the table (which avoids false positives from an optimistic
    parse).
    """
    by_name = {table.name: table for table in tables}
    indexed = {name: _indexed_columns(table) for name, table in by_name.items()}
    hints: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sql in sqls:
        for pattern in (_CORRELATED, _SIMPLE_WHERE):
            for table_name, column in pattern.findall(sql):
                table = by_name.get(table_name)
                key = (table_name, column)
                if (
                    table is not None
                    and column not in indexed[table_name]
                    and key not in seen
                    and any(c.name == column for c in table.columns)
                ):
                    seen.add(key)
                    hints.append(key)
    return hints


def index_hints_from_records(
    rows: Iterable[tuple[str, float]],
    tables: Iterable[SnakeTableInfo],
    *,
    min_ms: float = DEFAULT_MIN_MS,
) -> list[tuple[str, str, float]]:
    """SMART suggestions `(table, column, worst_ms)`: from the SLOW queries only.

    `rows` are `(sql, duration_ms)` pairs. Queries below `min_ms` are ignored (fast ones: an index
    changes nothing, it would be noise). From the slow ones, the unindexed filter columns are pulled
    out and the WORST duration per column is kept; the result comes ordered slowest first.
    """
    table_list = list(tables)
    worst: dict[tuple[str, str], float] = {}
    for sql, duration_ms in rows:
        if duration_ms < min_ms:
            continue
        for hint in index_hints_from_sql([sql], table_list):
            worst[hint] = max(worst.get(hint, 0.0), duration_ms)
    return sorted(
        ((table, column, ms) for (table, column), ms in worst.items()),
        key=lambda hint: hint[2],
        reverse=True,
    )
