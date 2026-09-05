"""`server_default`: the value is put there by the DB, not by the Python client.

A column carrying `server_default` (an engine-agnostic enum) or `server_default_sql` (raw SQL) is
EXCLUDED from the `__init__` and OMITTED from the INSERT: the database fills it in with its DEFAULT
and the RETURNING brings it back. If the user ASSIGNS the attribute before the insert, that value
DOES travel (just as an autoincrement id can be forced). Declaring it alongside `default` or
alongside `server_default_sql` is a contradiction —two sources for the same DEFAULT— and is
rejected loudly.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

import uuid
from datetime import datetime

import pytest

from snakeorm.decorators import snake_model, snake_table
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import MISSING, SnakeColumn, snake_auto, snake_column, snake_str

from snakeorm.metadata import SnakeServerDefault
from snakeorm.model import SnakeModel
from snakeorm.session.shared import insert_values


@snake_model(table="sd_notes")
class Note(SnakeModel):
    """A note with an autoincrement PK and two columns the server fills in."""

    id: SnakeColumn[int] = snake_auto()
    text: SnakeColumn[str] = snake_str()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    public_id: SnakeColumn[uuid.UUID] = snake_column(
        server_default=SnakeServerDefault.UUID_V4
    )


def test_server_default_excluded_from_init() -> None:
    """The column carrying server_default is NO constructor argument: it can be left out."""
    note = Note(text="hola")
    assert note.text == "hola"
    # Before the insert the attribute sits at the MISSING sentinel: the DB has not put it yet.
    assert note.created_at is MISSING
    assert note.public_id is MISSING


def test_passing_server_default_to_init_is_rejected() -> None:
    """Passing the column to the constructor is an unexpected argument, as the auto id is."""
    with pytest.raises(TypeError):
        Note(text="hola", created_at=datetime(2020, 1, 1))  # type: ignore[call-arg]


def test_server_default_omitted_from_insert() -> None:
    """The column carrying server_default is OMITTED from the INSERT so the DB puts its value."""
    note = Note(text="hola")
    values = insert_values(note, snake_table(Note))
    assert values == {"text": "hola"}  # no id (auto), no created_at, no public_id


def test_manual_assignment_travels_in_insert() -> None:
    """If the user assigns the attribute BEFORE the insert, that value DOES travel in the INSERT."""
    note = Note(text="hola")
    # WITH a zone and in UTC: the column holds an instant, and a naive datetime identifies none.
    note.created_at = SnakeUtc(2020, 1, 1)
    values = insert_values(note, snake_table(Note))
    assert values["created_at"] == SnakeUtc(2020, 1, 1)
    assert "public_id" not in values  # this one is still omitted (the DB puts it)


def test_metadata_carries_server_default() -> None:
    """The compiled graph keeps the agnostic ENUM, not the SQL: translating lives in the dialect."""
    table = snake_table(Note)
    created = table.get_column("created_at")
    assert created is not None
    assert created.server_default is SnakeServerDefault.NOW
    assert created.server_default_sql is None
    assert created.has_server_default is True


def test_server_default_and_sql_together_raise() -> None:
    """Declaring `server_default` and `server_default_sql` at once contradicts itself: error."""
    with pytest.raises(
        SnakeModelDefinitionError,
        match="Do not declare `server_default` and `server_default_sql` at",
    ):
        snake_column(server_default=SnakeServerDefault.NOW, server_default_sql="now()")


def test_server_default_and_default_together_raise() -> None:
    """`server_default` and `default` are two sources for the same DDL DEFAULT: error."""
    with pytest.raises(SnakeModelDefinitionError, match="Do not declare `default` and"):
        snake_column(server_default=SnakeServerDefault.NOW, default=5)


def test_server_default_sql_escape_hatch_is_stored() -> None:
    """The `server_default_sql` escape hatch (raw SQL, NOT portable) is stored exactly as given."""
    descriptor = snake_column(server_default_sql="now() + interval '1 day'")
    assert descriptor.server_default_sql == "now() + interval '1 day'"
    assert descriptor.server_default is None
    assert descriptor.has_server_default is True
