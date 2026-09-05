"""Conditionals inside the SQL: `CASE WHEN`, `COALESCE`, `NULLIF`.

They are VALUES, not conditions: a `CASE` returns a datum (it gets compared, projected, aggregated),
so it inherits from `SnakeValue`. The TYPE is pinned down by the constructors:
`snake_case((cond, 1), default=0)` is `SnakeValue[int]`, and projecting it types the tuple with no `Any`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar, overload

from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions.expression import SnakeCondition, SnakeValue

T = TypeVar("T")

# One branch of a CASE: if the condition holds, the value (a column or a literal).
SnakeCaseBranch = tuple[SnakeCondition, "SnakeValue[T] | T"]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeCase(SnakeValue[T]):
    """`CASE WHEN cond THEN value ... [ELSE default] END`.

    The branches are evaluated in order and the first match wins (the order is meaningful). Without
    a `default`, no `ELSE` is emitted (in SQL that already means NULL).
    """

    branches: tuple[SnakeCaseBranch[T], ...]
    default: SnakeValue[T] | T | None = None
    has_default: bool = False

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Paths of the columns it mentions (conditions, results and default), for the JOIN planner."""
        from snakeorm.expressions.paths import condition_paths

        collected: list[tuple[str, ...]] = []
        for condition, result in self.branches:
            collected.extend(condition_paths(condition))
            if isinstance(result, SnakeValue):
                collected.extend(result.paths())
        if isinstance(self.default, SnakeValue):
            collected.extend(self.default.paths())
        return tuple(collected)


@dataclass(frozen=True, slots=True, eq=False)
class SnakeCoalesce(SnakeValue[T]):
    """`COALESCE(a, b, ...)`: the first argument that is not NULL."""

    arguments: tuple[SnakeValue[T] | T, ...]

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Paths of the arguments that are columns."""
        return tuple(
            path
            for argument in self.arguments
            if isinstance(argument, SnakeValue)
            for path in argument.paths()
        )


@dataclass(frozen=True, slots=True, eq=False)
class SnakeNullIf(SnakeValue[T]):
    """`NULLIF(value, sentinel)`: NULL when the two are equal, and the value otherwise.

    `T` is the type of the RESULT —which carries the `| None` this node introduces— and not that of
    the operands, so the fields are stored untyped. Pinning them to `T` would demand a
    `SnakeValue[int | None]` where the caller has a `SnakeValue[int]`, and invariance refuses it.
    Same shape as `SnakeCoalesce`, which stores its arguments the same way and for the same reason:
    the constructor in this module is what pins the types down, which is where they belong.
    """

    value: SnakeValue[Any]
    sentinel: SnakeValue[Any] | Any

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Paths of the value and, if it is one, of the sentinel."""
        collected = list(self.value.paths())
        if isinstance(self.sentinel, SnakeValue):
            collected.extend(self.sentinel.paths())
        return tuple(collected)


_NO_DEFAULT = object()


# The overloads split the `SnakeValue[T] | T` union: together it is AMBIGUOUS (when passing
# `SnakeValue[str]`, `T` could be `str` or `SnakeValue[str]`, and mypy resolves it to `Never`). Split
# apart, each one pins `T` down.
@overload
def snake_case(*branches: SnakeCaseBranch[T]) -> SnakeCase[T]: ...
@overload
def snake_case(
    *branches: SnakeCaseBranch[T], default: SnakeValue[T]
) -> SnakeCase[T]: ...
@overload
def snake_case(*branches: SnakeCaseBranch[T], default: T) -> SnakeCase[T]: ...
def snake_case(
    *branches: SnakeCaseBranch[T], default: SnakeValue[T] | T | object = _NO_DEFAULT
) -> SnakeCase[T]:
    """Builds a `CASE WHEN`. The branches are evaluated in order; the first match wins.

        snake_case((User.age < 18, "minor"), (User.age < 65, "adult"), default="retired")

    Without a `default` it returns NULL when none of them match (SQL semantics).
    """
    if not branches:
        raise SnakeEmitError(
            "A CASE needs at least one branch (condition, value): with none there is no valid SQL "
            "to emit, only a stray ELSE."
        )
    if default is _NO_DEFAULT:
        return SnakeCase(branches=branches)
    return SnakeCase(
        branches=branches,
        default=default,  # type: ignore[arg-type]
        has_default=True,
    )


@overload
def snake_coalesce(first: SnakeValue[T], *rest: SnakeValue[T]) -> SnakeCoalesce[T]: ...


@overload
def snake_coalesce(first: SnakeValue[T | None], fallback: T, /) -> SnakeCoalesce[T]: ...


@overload
def snake_coalesce(
    first: SnakeValue[T], *rest: SnakeValue[T] | T
) -> SnakeCoalesce[T]: ...


def snake_coalesce(
    first: SnakeValue[Any], *rest: SnakeValue[Any] | Any
) -> SnakeCoalesce[Any]:
    """Builds a `COALESCE(...)`: the first non-NULL argument.

    The FIRST argument must be an expression: a literal there would never be NULL (it would always
    return that literal) and it also anchors the type `T`.

    THE MIDDLE OVERLOAD IS THE POINT: a `COALESCE` whose fallback is a LITERAL cannot be NULL, so it
    drops the `| None`. `COALESCE(SUM(x), 0)` is an `int`, and that is the entire reason anybody
    writes it — the value stops being nullable IN THE ENGINE, so it has to stop being nullable in the
    type. Without it the declarator that exists to remove a `None` handed one back, and the caller
    had to `cast()` in a project whose rule is zero `Any`.

    The first overload is what keeps that from becoming a lie: with every argument an expression,
    nothing guarantees a value and the nullability survives. Order matters — it has to be tried
    before the literal one, or an expression fallback would be read as the literal.
    """
    arguments: tuple[SnakeValue[Any] | Any, ...] = (first, *rest)
    if len(arguments) < 2:
        raise SnakeEmitError(
            "COALESCE needs at least two arguments: with only one it chooses nothing, it is the "
            "identity, and with zero there is nothing to choose from."
        )
    return SnakeCoalesce(arguments=arguments)


def snake_nullif(
    value: SnakeValue[T], sentinel: SnakeValue[T] | T
) -> SnakeNullIf[T | None]:
    """Builds a `NULLIF(value, sentinel)`: turns a sentinel (the empty string) into NULL.

    THE RESULT IS NULLABLE, and saying so is the whole point. This is the exact mirror of
    `snake_coalesce`, which REMOVES a `None` and declares it: this one PUTS one in. It used to
    return `SnakeNullIf[T]` — the same `T` it was given — so the declarator whose entire job is to
    introduce a NULL was the one place the type did not mention it.

    That is not a corner case. Guarding a division against zero is `x / snake_nullif(y, 0)`, and the
    NULL it produces IS the guard working. Typing that `int` told the caller the result could not be
    `None` in a project that asks people to trust the checker over the engine.
    """
    return SnakeNullIf(value=value, sentinel=sentinel)
