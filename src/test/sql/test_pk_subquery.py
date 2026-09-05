"""`pk IN (subquery)`: the rewrite of an UPDATE/DELETE whose filter navigates a relation.

It is the only module in `sql/` that did not have a single test of its own, and it just so happens to
be the path where getting it wrong stomps on rows nobody wanted touched. It was reached indirectly
-from the UPDATE and DELETE with join tests-, so it was EXERCISED but not VERIFIED: nobody checked
that the subquery projects only the PK, nor that the outer `IN` carries no alias, nor that a
composite PK uses the row constructor.

Why the rewrite exists: an `UPDATE ... FROM` is Postgres dialect slang and is not portable.
Projecting the PK with a subquery is, and on top of that it leaves the outer UPDATE operating on the
base table with no alias - which is what all three engines expect.
"""

from __future__ import annotations

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeDialect,
    SnakeExpr,
    SQLiteDialect,
)
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.sql.joins import JoinPlan
from snakeorm.sql.pk_subquery import emit_pk_in, emit_pk_subquery

_ID = SnakeColumnInfo(name="id", python_type=int)
_TENANT = SnakeColumnInfo(name="tenant_id", python_type=int)
_STATE = SnakeColumnInfo(name="estado", python_type=str)

_SIMPLE = SnakeTableInfo(
    name="invoices",
    columns=(_ID, _STATE),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)
_COMPUESTA = SnakeTableInfo(
    name="lines",
    columns=(_TENANT, _ID, _STATE),
    primary_key=SnakePrimaryKeyInfo(columns=(_TENANT, _ID)),
)


class _NoRelations:
    """A resolver for a plan with no relationships: it is never asked, and says so if it is.

    The old signature took a plain callable, so this was a `lambda _name: None`. Resolving through
    the RELATIONSHIP —which is what stops a JOIN landing on a homonymous table— needs an object, and
    the Protocol is one method wide precisely so a double like this stays this small.
    """

    def resolve_relationship(self, relationship: object) -> tuple[None, None]:
        """There are no relations in this plan; being called at all would be the surprise."""
        return None, None


def _plan(root: SnakeTableInfo = _SIMPLE) -> JoinPlan:
    """A plan with NO joins: enough for the pieces this module decides on its own.

    The deep paths are already covered by the UPDATE/DELETE with join tests; what was not verified
    here is what this module decides alone - what it projects, how it qualifies and how it numbers.
    """
    return JoinPlan(root, (), PostgresDialect(), _NoRelations())


def test_the_subquery_projects_only_the_primary_key() -> None:
    """It projects the PK and NOTHING else, with the root alias.

    If another column slipped in, the outer `IN` would compare tuples of different widths and the
    engine would reject it; and if it slipped in unnoticed on a composite PK, it would compare the
    wrong pair and delete somebody else's rows. That only the PK comes out here is the whole
    guarantee.
    """
    params: list[object] = []
    sql = emit_pk_subquery(
        _SIMPLE,
        PostgresDialect(),
        _plan(),
        SnakeExpr[str](path=("estado",)) == "x",
        params,
    )

    assert sql.startswith('SELECT t0."id" FROM')
    assert '"estado"' not in sql.split(" FROM ")[0], "only the PK in the projection"
    assert params == ["x"], "the value travels PARAMETRISED, not embedded"


def test_the_outer_in_has_no_alias_because_the_write_has_no_alias() -> None:
    """The outer `IN` goes UNqualified: the UPDATE/DELETE operates on the base table.

    Qualifying it with the subquery's alias is the natural mistake -both of them talk about the same
    column- and it produces SQL that does not compile, because that alias does not exist outside the
    subquery.
    """
    fuera = emit_pk_in(_SIMPLE, PostgresDialect(), "SELECT 1")

    assert fuera == '"id" IN (SELECT 1)'
    assert "t0" not in fuera


def test_a_composite_primary_key_uses_the_row_constructor() -> None:
    """With a composite PK, `(a, b) IN (...)`, and in the SAME order the table declares them.

    The order matters and it is not cosmetic: `(tenant_id, id) IN ((1, 7))` and `(id, tenant_id) IN ((1, 7))`
    select different rows, and both of them are valid SQL. A test that only looked at whether both
    columns show up would let the swap through.
    """
    fuera = emit_pk_in(_COMPUESTA, PostgresDialect(), "SELECT 1")

    assert fuera == '("tenant_id", "id") IN (SELECT 1)'


def test_every_engine_gets_its_own_quoting() -> None:
    """The module does not write identifiers on its own: it asks the dialect for them.

    That is what makes the rewrite portable, which is its whole reason for existing next to
    Postgres's `UPDATE ... FROM`.
    """
    expected: dict[type[SnakeDialect], str] = {}
    for dialect in (PostgresDialect(), MySQLDialect(), SQLiteDialect()):
        expected[type(dialect)] = emit_pk_in(_SIMPLE, dialect, "SELECT 1")

    assert expected[PostgresDialect] == '"id" IN (SELECT 1)'
    assert expected[MySQLDialect] == "`id` IN (SELECT 1)"
    assert expected[SQLiteDialect] == '"id" IN (SELECT 1)'


def test_the_subquery_names_the_table_with_its_schema() -> None:
    """The subquery qualifies the table by its schema, like the rest of the emission does.

    Without that, a model in a schema outside the default search path would select the PKs of another
    table with the same name - and the outer UPDATE would apply them without complaint.
    """
    in_schema = SnakeTableInfo(
        name="invoices",
        schema="analytics",
        columns=(_ID,),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )
    params: list[object] = []

    sql = emit_pk_subquery(
        in_schema,
        PostgresDialect(),
        _plan(in_schema),
        SnakeExpr[int](path=("id",)) > 0,
        params,
    )

    assert '"analytics"."invoices" AS t0' in sql


def test_the_where_params_continue_the_numbering_they_are_given() -> None:
    """The WHERE params ACCUMULATE on top of the ones the list already carried.

    It matters because the caller is the UPDATE, which has already put in the values of its `SET`: if
    this subquery restarted the numbering, each value would end up in the other one's placeholder. On
    a positional engine that does not fail - it writes the wrong thing.
    """
    params: list[object] = ["set-value"]

    emit_pk_subquery(
        _SIMPLE,
        PostgresDialect(),
        _plan(),
        SnakeExpr[str](path=("estado",)) == "pendiente",
        params,
    )

    assert params == ["set-value", "pendiente"]
