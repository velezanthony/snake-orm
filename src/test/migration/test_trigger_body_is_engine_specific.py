"""One trigger declaration, three engines: the DIALECT translates, the user writes it once.

A trigger body is written differently by every engine, and until this file existed the ORM sent it
through verbatim:

    PostgreSQL   a trigger CALLS a function; statements cannot go in the body
    SQLite       the statements go between BEGIN and END; without them it is a syntax error
    MySQL        a single statement goes bare

MEASURED against the real server: a body with inline statements emitted to PostgreSQL comes back
`syntax error at or near "UPDATE"`. So a declaration that ran on two engines broke on the third, and
the DRIVER is what said so — about a token, on SQL the user never wrote.

WHY TRANSLATING AND NOT REFUSING. The first attempt at this was a guard that rejected the wrong body
per engine, which is what the ORM does with things an engine CANNOT do. It is the wrong tool here:
PostgreSQL can hold this trigger perfectly, it just spells it with a function. Spelling is the
dialect's whole job — `quote_ident`, `placeholder`, `limit_offset` and `json_get_sql` are all the same
decision — and there is precedent one line over: SQLite has no `CREATE OR REPLACE VIEW`, so the
dialect rewrites it as `DROP` + `CREATE`. Refusing here would have made the user write the body three
times to say one thing.

SO A TRIGGER IS N STATEMENTS, NOT ONE. On PostgreSQL it is the function plus the trigger that calls
it; on the other two it is the trigger. `up_sql` already returned a list, so the shape was there
waiting — what was missing was the emitters returning what they actually produce.

AND DROPPING IT DROPS BOTH. A function left behind by a rolled-back migration is the kind of debris
nobody sees until a name collides.
"""

from __future__ import annotations

import pytest

from snakeorm import SnakeTriggerEvent, SnakeTriggerTiming
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.metadata import SnakeTriggerInfo
from snakeorm.migration import emit_create_trigger, emit_drop_trigger

_BODY = "UPDATE posts SET visit_count = visit_count + 1 WHERE id = NEW.post_id;"


def _trigger() -> SnakeTriggerInfo:
    """A trigger that keeps a denormalised counter, over the volume table."""
    return SnakeTriggerInfo(
        name="tg_visits",
        table="visits",
        timing=SnakeTriggerTiming.AFTER,
        events=(SnakeTriggerEvent.INSERT,),
        body=_BODY,
    )


def test_postgres_wraps_the_body_in_a_function_and_calls_it() -> None:
    """TWO statements: the function that holds the body, and the trigger that calls it."""
    statements = emit_create_trigger(_trigger(), PostgresDialect())

    assert len(statements) == 2, statements
    assert statements[0].startswith("CREATE OR REPLACE FUNCTION")
    assert "RETURNS trigger" in statements[0]
    assert _BODY in statements[0]
    assert statements[1].endswith('EXECUTE FUNCTION "tg_visits_fn"()')


@pytest.mark.parametrize(
    "dialect", [SQLiteDialect(), MySQLDialect()], ids=["sqlite", "mysql"]
)
def test_the_inline_engines_emit_one_statement_with_the_body_in_it(
    dialect: object,
) -> None:
    """One statement, the body where it goes. Nothing is wrapped that does not need wrapping."""
    statements = emit_create_trigger(_trigger(), dialect)  # type: ignore[arg-type]

    assert len(statements) == 1, statements
    assert _BODY in statements[0]
    assert "FUNCTION" not in statements[0]


def test_postgres_drops_the_function_it_created() -> None:
    """Dropping the trigger drops its function too: a rollback leaves nothing behind.

    The order matters and is asserted: the trigger DEPENDS on the function, so the function cannot go
    first. Getting this backwards fails only on rollback, which is the run nobody watches.
    """
    statements = emit_drop_trigger(_trigger(), PostgresDialect())

    assert len(statements) == 2, statements
    assert statements[0].startswith('DROP TRIGGER "tg_visits"')
    assert statements[1] == 'DROP FUNCTION IF EXISTS "tg_visits_fn"()'


@pytest.mark.parametrize(
    "dialect", [SQLiteDialect(), MySQLDialect()], ids=["sqlite", "mysql"]
)
def test_the_inline_engines_drop_only_the_trigger(dialect: object) -> None:
    """They created no function, so there is none to drop."""
    statements = emit_drop_trigger(_trigger(), dialect)  # type: ignore[arg-type]

    assert len(statements) == 1, statements
    assert "FUNCTION" not in statements[0]


def test_a_body_that_already_calls_a_function_is_left_alone_on_postgres() -> None:
    """Somebody who wrote the PostgreSQL shape by hand keeps it: this wraps, it does not second-guess.

    The dialect translates what needs translating. A body that is already `EXECUTE FUNCTION ...` is
    the shape PostgreSQL wants, and wrapping it would produce a function that calls a function.
    """
    declared = SnakeTriggerInfo(
        name="tg_audit",
        table="orders",
        timing=SnakeTriggerTiming.AFTER,
        events=(SnakeTriggerEvent.UPDATE,),
        body="EXECUTE FUNCTION audit_orders();",
    )

    statements = emit_create_trigger(declared, PostgresDialect())

    assert len(statements) == 1, statements
    assert statements[0].endswith("EXECUTE FUNCTION audit_orders();")


def test_sqlite_wraps_the_body_in_begin_end() -> None:
    """The third spelling, and the one that was found by RUNNING the demo's migrations.

    SQLite refuses a bare statement after `FOR EACH ROW` — measured, `near "UPDATE": syntax error` —
    even for a single one. That is what makes this three implementations and not two: it is not
    "PostgreSQL versus the rest", each engine is different from the other two.
    """
    statements = emit_create_trigger(_trigger(), SQLiteDialect())

    assert len(statements) == 1, statements
    assert statements[0].endswith(f"BEGIN {_BODY} END")


def test_mysql_leaves_a_single_statement_bare() -> None:
    """And MySQL takes it without wrapping, which is why SQLite's `BEGIN`/`END` is not universal."""
    statements = emit_create_trigger(_trigger(), MySQLDialect())

    assert len(statements) == 1, statements
    assert statements[0].endswith(_BODY)
    assert "BEGIN" not in statements[0]


def test_sqlite_leaves_a_body_that_is_already_wrapped() -> None:
    """The symmetry PostgreSQL had and SQLite did not, written into the same method that lacked it.

    A body somebody wrote as `BEGIN ... END` is already the SQLite shape. Wrapping it again produced
    `BEGIN BEGIN SELECT 1; END END`, and the engine answered `near "BEGIN": syntax error` — found by
    a fixture that had been declaring its trigger that way all along.

    It is the same rule as `test_a_body_that_already_calls_a_function_is_left_alone_on_postgres`, and
    the fact that it had to be written twice is the point: the rule was applied to one dialect and
    not to its neighbour, in the same change.
    """
    declared = SnakeTriggerInfo(
        name="tg_wrapped",
        table="visits",
        timing=SnakeTriggerTiming.AFTER,
        events=(SnakeTriggerEvent.INSERT,),
        body="BEGIN SELECT 1; END",
    )

    statements = emit_create_trigger(declared, SQLiteDialect())

    assert len(statements) == 1, statements
    assert statements[0].endswith("BEGIN SELECT 1; END")
    assert "BEGIN BEGIN" not in statements[0]
