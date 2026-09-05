"""Immutable metadata of a compiled model (the graph's root node)."""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.core.placement import DEFAULT_DATABASE, DEFAULT_SCHEMA
from snakeorm.metadata.check import SnakeCheckInfo
from snakeorm.metadata.column import SnakeColumnInfo
from snakeorm.metadata.index import SnakeIndexInfo
from snakeorm.metadata.polymorphic import SnakePolymorphicInfo
from snakeorm.metadata.primary_key import SnakePrimaryKeyInfo
from snakeorm.metadata.relationship import SnakeRelationshipInfo
from snakeorm.metadata.table_kind import SnakeTableKind


@dataclass(frozen=True, slots=True)
class SnakeTableInfo:
    """Compiled model: name, columns, primary key, relations and indexes.

    This is the graph's root node. The whole ORM (SQL, migrations, query) reads from here;
    the runtime never inspects the class again.
    """

    name: str
    columns: tuple[SnakeColumnInfo, ...]
    primary_key: SnakePrimaryKeyInfo
    relationships: tuple[SnakeRelationshipInfo, ...] = ()
    schema: str = DEFAULT_SCHEMA
    # Connection the node lives on. An axis INDEPENDENT of `kind` (what it is vs where it lives).
    database: str = DEFAULT_DATABASE
    db_comment: str | None = None  # COMMENT ON TABLE
    indexes: tuple[SnakeIndexInfo, ...] = ()
    # Domain rules the DB enforces (`CHECK (...)`). Condition as an AST, not emitted SQL.
    checks: tuple[SnakeCheckInfo, ...] = ()
    # What the node IS and who governs it, one single axis instead of booleans: see `SnakeTableKind`.
    kind: SnakeTableKind = SnakeTableKind.TABLE
    view_definition: str | None = None  # the view's RAW SELECT (only with `sql=`)
    view_query: object = None
    """The `SnakeQuery` that defines the view, uncompiled (only with `query=`).

    It is stored UNCOMPILED on purpose: a view's body is written differently on every engine
    —quoting, schema qualification, literals, LIMIT/OFFSET— and compiling it at model declaration
    time froze it into one engine's. The emitter is the one that compiles it, with the target
    dialect.

    Typed `object` and not `SnakeQuery` because `metadata/` sits BELOW `query/` in the layer graph:
    annotating it with its real type would invert the dependency. Whoever uses it narrows it.
    """
    # EXPLICIT dependencies of this view on OTHER views (resolved names). Forces the migration's
    # topological order (create A before B). Only between views; empty on a normal table.
    depends_on: tuple[str, ...] = ()
    # Participation in a POLYMORPHIC hierarchy. `None` on a normal table. Another axis independent
    # of `kind`/`database`: see `SnakePolymorphicInfo`.
    polymorphic: SnakePolymorphicInfo | None = None

    @property
    def is_polymorphic_child(self) -> bool:
        """Whether it is a CHILD of a hierarchy: shares a table with the base, filtered by its value.

        Since the physical table is a single one: autogen does NOT emit its `CREATE TABLE` (the base
        does) and queries DO filter it by its discriminator.
        """
        return self.polymorphic is not None and not self.polymorphic.is_base

    @property
    def is_view(self) -> bool:
        """Whether the node is a VIEW (read only, no constraints). Derived from `kind`."""
        return self.kind is SnakeTableKind.VIEW

    @property
    def is_managed(self) -> bool:
        """Whether MIGRATIONS govern this node.

        An `EXTERNAL` mirror (`@snake_db_first`) is queried and written like any other model, but
        autogen ignores it: its schema is governed by the DB, not by us.
        """
        return self.kind is not SnakeTableKind.EXTERNAL

    def get_column(self, name: str) -> SnakeColumnInfo | None:
        """Returns the column with that SQL name, or None if it does not exist."""
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def get_column_by_attr(self, attr: str) -> SnakeColumnInfo | None:
        """Returns the column whose Python ATTRIBUTE is `attr`, or None if it does not exist.

        With `snake_column(name=...)` the SQL name and the attribute's differ, and whoever walks the
        graph uses the attribute. It tries `attr_name` and falls back to the SQL name (hand-written
        metadata may not carry it).
        """
        for column in self.columns:
            if column.attr_name == attr:
                return column
        return self.get_column(attr)
