"""Every dialect answers for the WHOLE scalar catalogue: it translates a function or declares it.

`SnakeFunc` is agnostic, and each dialect maps it onto its own spelling. What there was no way to
say was "this engine cannot do that one" — a function simply missing from the table read exactly
like a function nobody had got round to. Absence meant both, and the two are not the same thing.

Measured: `ABS` and `ROUND` were absent from SQLite while Postgres and MySQL had both. They are core
SQLite functions, present in every build, so nothing was being declared — they had been forgotten,
and a model that ran on two engines raised `SQLiteDialect does not know how to translate` on the
third. Nothing was red, because no test ever walked the catalogue.

So a dialect now answers for every member, the same way it answers the whole `Cap` catalogue, and
forgetting one is an ImportError rather than a surprise at runtime.
"""

from __future__ import annotations

import pytest

from snakeorm import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.expressions.scalar import SnakeFunc
from snakeorm.dialects.base import SnakeDialect

_DIALECTS = [PostgresDialect(), MySQLDialect(), SQLiteDialect()]


def _name(dialect: SnakeDialect) -> str:
    """The dialect's class name, for a test id you can read in a failure."""
    return type(dialect).__name__


@pytest.mark.parametrize(
    "dialect, func",
    [(dialect, func) for dialect in _DIALECTS for func in SnakeFunc],
    ids=lambda value: value.name if isinstance(value, SnakeFunc) else _name(value),
)
def test_every_dialect_answers_for_every_function(
    dialect: SnakeDialect, func: SnakeFunc
) -> None:
    """A dialect translates the function, or refuses it NAMING it and saying why.

    One test per pair on purpose: a failure names the engine and the function to fix, instead of
    handing back a set to diff by eye. And an unsupported one still has to answer — silence would
    put us back where this started.
    """
    try:
        spelling = dialect.function_name(func)
    except SnakeDialectError as refusal:
        assert func.name in str(refusal), (
            f"{_name(dialect)} refuses {func.name} without naming it: {refusal}"
        )
        assert str(refusal).rstrip().endswith((".", ")")), (
            f"{_name(dialect)} refuses {func.name} without saying why: {refusal}"
        )
        return

    assert spelling, f"{_name(dialect)} translates {func.name} to nothing"


@pytest.mark.parametrize("dialect", _DIALECTS, ids=_name)
@pytest.mark.parametrize("func", [SnakeFunc.ABS, SnakeFunc.ROUND], ids=lambda f: f.name)
def test_the_core_maths_functions_work_on_all_three(
    dialect: SnakeDialect, func: SnakeFunc
) -> None:
    """`ABS` and `ROUND` are named on every engine, so no model can run on two and fail on the third.

    Named one by one rather than left to the sweep above, because the sweep is satisfied by a clean
    refusal and these two have nothing to refuse: every SQLite build ships them, unlike `CEIL` and
    friends, which are a compile-time option. A refusal here would be a lie about the engine.
    """
    assert dialect.function_name(func) == func.name
