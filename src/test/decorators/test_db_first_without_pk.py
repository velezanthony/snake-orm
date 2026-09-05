"""A `@snake_db_first` mirror of a table WITHOUT a primary key.

DB-first hands control of the schema to the sysadmin: the ORM is a CLIENT that queries and writes
rows, not the owner of the structure. And legacy schemas —which are the whole reason DB-first
exists— are full of tables with no PK: logs, staging, imports, crossing tables.

Demanding a PK from a mirror was inventing a rule the database does not impose. The very same
exception views already had, and for the very same reason: we are not the ones declaring it.

What is NOT relaxed is whatever depends on the PK to be correct. With no PK there is no row
identity, so equality falls back to identity and writes BY PK are refused out loud. That is not a
limitation: it is the truth about a table that cannot tell its own rows apart.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    snake_db_first,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.registry import SnakeRegistry

_REG = SnakeRegistry()


@snake_db_first(table="pk_less_events", registry=_REG)
class LegacyEvent(SnakeModel):
    """Mirror of a log table with no PK: the canonical case of an inherited schema."""

    source: SnakeColumn[str] = snake_str()
    mensaje: SnakeColumn[str] = snake_str()


def test_an_external_mirror_compiles_without_a_primary_key() -> None:
    """The mirror compiles with no PK: the table has none and it is not ours to invent one."""
    table = _REG.table_of(LegacyEvent)
    assert table is not None
    assert table.primary_key.columns == ()
    assert table.is_managed is False


def test_a_managed_model_still_demands_a_primary_key() -> None:
    """The relaxation is ONLY for mirrors: whatever we govern still demands a PK.

    This is the half that makes the other one correct. If the model is ours, the PK is a decision we
    took ourselves, and leaving it out is an oversight, not a fact about the database.
    """
    with pytest.raises(
        SnakeModelDefinitionError, match="has to declare at least one PK"
    ):

        @snake_model(table="pk_less_nuestra", registry=SnakeRegistry())
        class OursWithoutPk(SnakeModel):
            """A managed model that is missing its PK."""

            name: SnakeColumn[str] = snake_str()


def test_two_rows_without_a_primary_key_are_not_equal() -> None:
    """With no PK, equality falls back to IDENTITY, not to 'everything is equal'.

    With an empty PK, comparing its values means comparing `() == ()`, which is true ALWAYS. That
    would make two different rows equal and a `set` of a hundred events would shrink to one: data
    loss inside the user's code, silent and hard to trace back here.
    """
    first = LegacyEvent(source="cron", mensaje="arranque")
    second = LegacyEvent(source="cron", mensaje="parada")

    assert first != second
    assert first == first


def test_rows_without_a_primary_key_survive_a_set() -> None:
    """The practical consequence: a `set` keeps the rows instead of collapsing them."""
    rows = [LegacyEvent(source="cron", mensaje=f"line {i}") for i in range(5)]

    assert len(set(rows)) == 5


def test_writing_by_primary_key_is_refused_out_loud() -> None:
    """`update`/`delete`/`refresh` over a table with no PK are refused WITH a reason.

    With no PK there is no condition that identifies a row. The condition came out empty and
    Postgres rejected it with `syntax error at or near ")"`, which tells nobody what is really going
    on: that this table cannot tell its own rows apart. The guard belongs in the ORM, not in the
    engine.

    Inserting IS allowed: being a client of somebody else's database includes writing rows into it.
    What cannot be done is EDITING one particular row when there is no way of naming it.
    """
    from snakeorm import PostgresDialect
    from snakeorm.core.exceptions import SnakeUnsupportedFeature
    from snakeorm.session import SnakeSession

    # A driver that BLOWS UP if anyone touches it: the guard has to fire before anything is
    # emitted, and this way the test proves it instead of assuming it.
    class UnusedDriver:
        """Any use at all is a failure of the test."""

        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"the guard had to fire before using .{name}()")

    session = SnakeSession(cast("Any", UnusedDriver()), PostgresDialect())
    event = LegacyEvent(source="cron", mensaje="x")
    # No monkeypatch of the global registry any more, and its absence is the point: the mirror
    # carries its own registry (`__snake_registry__`, which `@snake_db_first` did not use to record)
    # and the session asks the MODEL. Patching a global to make a private registry visible was the
    # workaround for a defect that is now fixed.

    for operation in (session.update, session.delete, session.refresh):
        with pytest.raises(SnakeUnsupportedFeature, match="has no primary key"):
            operation(cast("Any", event))
