"""Function autodetect: the store of desired routines is diffed against the history.

`snake_function(name=..., body=...)` declares a DESIRED function in the registry (a routine store
kept apart from the models). Autodetect compares it against the replayed state of the history: new
→ CreateFunction, `body` changed → AlterFunction, removed from the store → DropFunction, no change
→ nothing. The change comparison is purely on the `body` string (the routine is opaque).
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_function
from snakeorm.metadata import SnakeRoutineInfo
from snakeorm.migration import (
    AlterFunction,
    CreateFunction,
    DropFunction,
    Migration,
    autodetect,
    current_routines,
)
from snakeorm.registry import registry

_BODY = (
    "CREATE OR REPLACE FUNCTION fa_fn() RETURNS integer AS $$ SELECT 1 $$ LANGUAGE sql"
)
_BODY_V2 = _BODY.replace("SELECT 1", "SELECT 2")


@pytest.fixture
def clean_routines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the routine store of the global registry (empty on entry, restored on exit)."""
    monkeypatch.setattr(registry, "_routines", {})


def _history_with(routine: SnakeRoutineInfo) -> list[Migration]:
    """A history of one migration creating the given routine (to simulate the replayed state)."""
    return [Migration(version="0001", operations=(CreateFunction(routine),))]


def test_new_function_emits_create(clean_routines: None) -> None:
    """A declared function that is not in the history produces a CreateFunction."""
    snake_function(name="fa_fn", body=_BODY)
    operations = autodetect([], [], current_routines())
    assert len(operations) == 1
    assert isinstance(operations[0], CreateFunction)
    assert operations[0].definition.name == "fa_fn"
    assert operations[0].definition.body == _BODY


def test_changed_body_emits_alter(clean_routines: None) -> None:
    """If the `body` changes relative to the history, an AlterFunction is emitted (old → new)."""
    snake_function(name="fa_fn", body=_BODY_V2)
    history = _history_with(SnakeRoutineInfo(name="fa_fn", body=_BODY))
    operations = autodetect(history, [], current_routines())
    assert len(operations) == 1
    assert isinstance(operations[0], AlterFunction)
    assert operations[0].old.body == _BODY
    assert operations[0].new.body == _BODY_V2


def test_removed_function_emits_drop(clean_routines: None) -> None:
    """A function from the history that is no longer in the store produces a DropFunction."""
    history = _history_with(SnakeRoutineInfo(name="fa_fn", body=_BODY))
    operations = autodetect(history, [], current_routines())
    assert len(operations) == 1
    assert isinstance(operations[0], DropFunction)
    assert operations[0].definition.name == "fa_fn"


def test_no_change_emits_nothing(clean_routines: None) -> None:
    """A function identical in store and history produces no operation at all (it converges)."""
    snake_function(name="fa_fn", body=_BODY)
    history = _history_with(SnakeRoutineInfo(name="fa_fn", body=_BODY))
    assert autodetect(history, [], current_routines()) == []


def test_current_routines_reads_the_registry(clean_routines: None) -> None:
    """`current_routines()` is the source of truth: it reflects what `snake_function` registered."""
    routine = snake_function(name="fa_fn", body=_BODY)
    assert list(current_routines()) == [routine]
