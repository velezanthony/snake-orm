"""A view declared with `query=` stops being a Postgres view.

`@snake_view(query=...)` instantiated a `PostgresDialect()` INSIDE the decorator, at import time,
and compiled the body of the view right there. That froze the quoting, the schema qualification,
the literal formatting and the `LIMIT/OFFSET` of one particular engine —for every engine— and it
was on top of that the one and only `decorators/ -> dialects/` edge in the package.

The knot was not in the decorator but downstream: `render.py` serialises the definition as a string
into the snapshot and `diff.py` compares views by equality of that string. Storing the `SnakeQuery`
uncompiled broke both routes, which is why the "obvious" fix —deferring the compilation to the
emitter— did not work as it stood.

The way out is to split the two things that string was doing at once:

- The comparison **fingerprint**, computed with a CANONICAL dialect and never executed. It exists to
  tell whether a view changed, and that is why it has to be identical across the three engines: were
  it to depend on the engine, the same model would generate a different migration on every machine.
- The real **DDL**, which each engine emits with its own dialect at the moment of creating the view.

And along the way the decorator no longer imports any dialect: the fingerprint is computed by
`migration/`, a layer that is allowed to know about engines.
"""

from __future__ import annotations

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeColumn,
    SnakeQuery,
    SnakeView,
    SQLiteDialect,
    snake_auto,
    snake_model,
    snake_str,
    snake_view,
)
from snakeorm.migration import ddl
from snakeorm.registry import SnakeRegistry, registry


# In the GLOBAL registry on purpose: `SnakeQuery` resolves the model there, so a view declared with
# `query=` cannot be mounted in an isolated store. The names carry a prefix so they do not collide.
@snake_model(table="vd_parts")
class VdPart:
    """Base table the view of this test is defined over."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=50)


@snake_view(
    query=SnakeQuery(VdPart).filter(VdPart.name == "screw").limit(10),
    name="vd_parts_screw",
)
class VdPartScrew(SnakeView):
    """View declared with `query=`, which is the path that was hard-wired to Postgres."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=50)


def _view() -> object:
    """The compiled metadata of the view, exactly as a migration would use it."""
    table = registry.table_of(VdPartScrew)
    assert table is not None
    return table


def test_each_engine_writes_the_view_body_in_its_own_dialect() -> None:
    """The body of the view compiles with the TARGET dialect, not with a fixed one.

    The `LIMIT` is what gives it away beyond doubt: MySQL parameterises it differently and SQLite
    demands a `LIMIT` before the `OFFSET`. Comparing the quoting alone would be flimsier.
    """
    view = _view()
    on_postgres = ddl.emit_create_view(view, PostgresDialect())  # type: ignore[arg-type]
    on_mysql = ddl.emit_create_view(view, MySQLDialect())  # type: ignore[arg-type]
    on_sqlite = ddl.emit_create_view(view, SQLiteDialect())  # type: ignore[arg-type]

    assert '"vd_parts"' in on_postgres, "Postgres quotes with double quotes"
    assert "`vd_parts`" in on_mysql, "MySQL quotes with backticks"
    assert '"vd_parts"' in on_sqlite
    assert on_postgres != on_mysql, "the body can NOT be the same on all three"


def test_the_comparison_fingerprint_is_the_same_on_every_engine() -> None:
    """The FINGERPRINT does not depend on the engine. That is the golden rule of the snapshot.

    Were it to depend on it, the same model would generate a different migration depending on which
    machine ran `makemigrations`, and two devs on different engines would trample the history.
    """
    view = _view()

    fingerprints = {
        ddl.view_fingerprint(view)  # type: ignore[arg-type]
        for _ in range(3)
    }

    assert len(fingerprints) == 1
    assert "vd_parts" in next(iter(fingerprints))


def test_a_view_declared_with_raw_sql_is_left_exactly_as_written() -> None:
    """The `sql=` path is left alone: the user wrote it in the dialect of their own engine.

    Recompiling it would be impossible (there is no query to compile) and rewriting it would be
    worse: this ORM does not reinterpret anybody's raw SQL.
    """
    registry = SnakeRegistry()

    @snake_view(sql='SELECT 1 AS "id"', name="cruda", registry=registry)
    class Cruda(SnakeView):
        """View whose SELECT was written by hand."""

        id: SnakeColumn[int] = snake_auto()

    table = registry.table_of(Cruda)
    assert table is not None

    assert ddl.view_fingerprint(table) == 'SELECT 1 AS "id"'
    assert 'SELECT 1 AS "id"' in ddl.emit_create_view(table, MySQLDialect())


def test_the_view_decorator_no_longer_imports_a_dialect() -> None:
    """The one and only `decorators/ -> dialects/` edge of the package is gone.

    This is no cosmetic tidy-up: as long as the decorator instantiated a dialect, the layer that
    declares the models knew about engines, and the golden rule of this project is that it must not.
    """
    import pathlib

    source = pathlib.Path("src/snakeorm/decorators/view.py").read_text(encoding="utf-8")

    assert "dialects" not in source
