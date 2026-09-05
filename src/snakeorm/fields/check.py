"""Declaring CHECK constraints: `snake_check(...)` in the body of the model."""

from __future__ import annotations

from dataclasses import replace

from snakeorm.core.exceptions import SnakeModelError
from snakeorm.expressions import SnakeCondition
from snakeorm.fields.index import SnakeIndex
from snakeorm.metadata import SnakeIndexInfo
from snakeorm.fields.relationship import _registry_of
from snakeorm.metadata.check import SnakeCheckInfo


def snake_check(
    condition: SnakeCondition, *, name: str | None = None
) -> SnakeCheckInfo:
    """Declare a typed CHECK constraint: the condition is the same `SnakeCondition` as
    `.filter()`.

    It gets validated here, at declaration time, and not when generating the migration: a
    condition with a subquery or an EXISTS does not fit in a CHECK, and the useful place to find
    out is where you wrote it.
    """
    info = SnakeCheckInfo(condition=condition, name=name)
    # A dry render so the rejection fires now; `render_condition` is the only one that knows which
    # nodes are reconstructible (duplicating that criterion would mean having two truths).
    from snakeorm.migration.render import render_condition

    render_condition(condition)
    return info


def snake_checks(model: type, *checks: SnakeCheckInfo) -> None:
    """Add CHECK constraints to an ALREADY decorated model, referencing its TYPED columns.

        snake_checks(Person, snake_check(Person.age >= 18, name="adult"))

    Outside the class body (not inside it like `SnakeIndexes`) because a condition is built on the
    spot and inside the body `age` is the raw descriptor, with `__set_name__` not yet run: it does
    not know its name yet. Once decorated, `Person.age` is CLASS access → `SnakeExpr[int]`, which
    preserves the typing.
    """
    reg = _registry_of(model)
    table = reg.table_of(model)
    if table is None:
        raise SnakeModelError(
            f"{model.__name__} is not a @snake_model: declare the model before adding checks to it."
        )
    reg.register(model, replace(table, checks=(*table.checks, *checks)))


def snake_indexes(model: type, *indexes: SnakeIndex) -> None:
    """Add indexes to an ALREADY decorated model, referencing its TYPED columns.

        snake_indexes(Customer, SnakeIndex(Customer.name, unique=True, where=Customer.closed_at.is_null()))

    Same reason as `snake_checks`: a PARTIAL index needs a condition, which is built on the spot
    and does not fit in the `SnakeIndexes` of the body. It re-registers the model instead of
    mutating an attribute (assigning `SnakeIndexes` after the decorator never reaches the graph:
    it has already compiled).
    """
    reg = _registry_of(model)
    table = reg.table_of(model)
    if table is None:
        raise SnakeModelError(
            f"{model.__name__} is not a @snake_model: declare the model before adding indexes to it."
        )
    compiled = tuple(
        SnakeIndexInfo(
            columns=index.column_names(),
            unique=index.unique,
            name=index.name,
            where=index.where,
            method=index.method,
        )
        for index in indexes
    )
    reg.register(model, replace(table, indexes=(*table.indexes, *compiled)))
