"""The @snake_view decorator: it maps a database VIEW as a READ-ONLY model."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, TypeAlias, TypeVar, dataclass_transform

from snakeorm.compiler import compile_model
from snakeorm.decorators.model import _install_dunders, _make_init
from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import (
    snake_auto,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_float,
    snake_time,
    snake_timetz,
    snake_decimal,
    snake_discriminator,
    snake_enum,
    snake_int,
    snake_json,
    snake_str,
    snake_to_many,
    snake_to_many_through,
    snake_to_one,
)
from snakeorm.metadata import SnakeTableKind
from snakeorm.query import SnakeCompound, SnakeQuery
from snakeorm.registry import SnakeRegistry
from snakeorm.registry import registry as default_registry

T = TypeVar("T")

SnakeViewBody: TypeAlias = "SnakeQuery[Any] | SnakeCompound[Any]"
"""What may DEFINE a view: one SELECT, or a set operation over several.

A compound was always executed correctly here —`view_body` only asks the object for `to_sql`, and
it was measured creating and querying the view on the three engines— and the annotation still said
`SnakeQuery`, which sent the caller to a `# type: ignore` over something the ORM does properly. A
view over a `UNION` is half the views there are.

`SnakeRecursive` is deliberately NOT here: a `WITH` inside a `CREATE VIEW` is its own question per
engine, and it has not been measured. What is declared is what has been.
"""


def _view_source(sql: str | None, query: SnakeViewBody | None) -> None:
    """Demand EXACTLY one source for the view definition (both or neither is an error)."""
    if (sql is None) == (query is None):
        raise SnakeModelDefinitionError(
            "@snake_view requires EXACTLY one source for the definition: `sql=` (a raw SELECT) "
            "or `query=` (a SnakeQuery, or a UNION/EXCEPT/INTERSECT of them) — never both, and "
            "never neither."
        )


def _dependency_name(dep: type, reg: SnakeRegistry) -> str:
    """Resolve a `depends_on` class to the NAME of its view (we store names, not classes).

    It only admits OTHER `@snake_view` views (already registered). If it is not registered or is
    not a view, that is an error: a view does not depend on a table through `depends_on` (tables
    are always created first).
    """
    # It is looked up in the SAME registry where the view is declared: an isolated view of that
    # same store would not be found in the global one, and the error would say "it is not a view"
    # when it very much is.
    table = reg.table_of(dep)
    if table is None or not table.is_view:
        raise SnakeModelDefinitionError(
            f"depends_on on @snake_view only admits OTHER @snake_view views; "
            f"{getattr(dep, '__name__', dep)!r} is not a registered view. A view is always created "
            f"after ALL the tables, so tables are never declared in depends_on."
        )
    return table.name


# A LITERAL tuple as PEP 681 demands; tied to SNAKE_FIELD_SPECIFIERS by a test.
@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        snake_column,
        snake_auto,
        snake_enum,
        snake_int,
        snake_str,
        snake_decimal,
        snake_datetime,
        snake_datetimetz,
        snake_float,
        snake_time,
        snake_timetz,
        snake_json,
        snake_to_one,
        snake_to_many,
        snake_to_many_through,
        snake_discriminator,
    ),
)
def snake_view(
    *,
    sql: str | None = None,
    query: SnakeViewBody | None = None,
    name: str | None = None,
    schema: str = DEFAULT_SCHEMA,
    depends_on: Sequence[type] = (),
    registry: SnakeRegistry = default_registry,
) -> Callable[[type[T]], type[T]]:
    """Compile a `SnakeView` class as a READ-ONLY database VIEW.

    The same TYPED columns as a model, but the node is marked `kind=SnakeTableKind.VIEW` and it
    holds the SELECT (`view_definition`). Creating/editing/dropping it lives in the migrations, not
    in the session. Relation navigation works in both directions as pure SQL generation: the DB
    does not guarantee the FK of a view.

    `depends_on` lists the OTHER `@snake_view` views that THIS one reads: the migration creates it
    AFTER them (topological order) and drops it BEFORE. Only between views (a view gets created
    after ALL the tables).

    `registry` lets you declare it in an ISOLATED store, just like `@snake_model` and
    `@snake_db_first`.
    """
    _view_source(sql, query)

    def wrap(klass: type[T]) -> type[T]:
        dependencies = tuple(_dependency_name(dep, registry) for dep in depends_on)
        table = compile_model(
            klass, table=name, schema=schema, kind=SnakeTableKind.VIEW
        )
        registry.register(
            klass,
            replace(
                table,
                # The query is stored UNCOMPILED: the body of a view is written differently on
                # each engine, and compiling it here froze it into one of them. The emitter
                # compiles it.
                view_definition=sql,
                view_query=query,
                depends_on=dependencies,
            ),
        )
        setattr(klass, "__init__", _make_init(klass))
        _install_dunders(klass, registry)
        return klass

    return wrap
