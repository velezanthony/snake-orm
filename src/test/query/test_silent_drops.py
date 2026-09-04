"""A bulk write must refuse EVERY knob it does not emit, and the list cannot be written by hand.

`_guard_bulk_write` named six of the ten knobs in one `or` chain. The four it forgot —`distinct()`,
`for_update()`, `only()`/`defer()` and a bare prefetch— were dropped in silence: a
`session.delete_where(query.distinct())` emitted a plain `DELETE ... WHERE` and answered a different
question from the one that was asked, which is the worst shape a failure can take.

The project had already diagnosed this on itself. `query.py` says, about the other guard: "that is
the difference between this and `_guard_bulk_write`, which lists its knobs by hand and is one `or`
away from the same hole". The hole was already four wide.

THE TRAP, and it is the reason this file has a test about zero in it: `_guard_unsupported` decides
by TRUTHINESS. `limit(0)` and `offset(0)` are legal and falsy, so a guard derived that way lets
`delete_where(query.limit(0))` through as though no limit had been set — and emits a `DELETE` with
no limit at all, destroying every row that matches where the caller asked for none. The predicate
has to compare against a PRISTINE query, not ask whether the value is truthy.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakeColumn, snake_int, snake_str
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.query.query import _NOT_A_KNOB
from test.scenarios.deep_domain import Maker


@snake_model(table="sd_users")
class _User(SnakeModel):
    """Test model for the bulk-write guard."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


snake_link()

_DIALECT = PostgresDialect()

# One caller per knob, so the parametrisation names the knob that slipped through instead of a
# slot. Every one of these is a question the caller asked that a bulk write does not answer.
_KNOBS: dict[str, Callable[[SnakeQuery[_User]], SnakeQuery[_User]]] = {
    "_order": lambda q: q.order_by(_User.id),
    "_limit": lambda q: q.limit(5),
    "_offset": lambda q: q.offset(5),
    "_group_by": lambda q: q.group_by(_User.name),
    "_having": lambda q: q.having(_User.id > 1),
    "_distinct": lambda q: q.distinct(),
    "_lock": lambda q: q.for_update(),
    "_columns": lambda q: q.only(_User.name),
}

# `_includes` and `_prefetches` live on a model that HAS a to-many, and they are the pair that
# `include()` splits across: naming one of the two slots in an `or` chain —which is what the old
# guard did— leaves the other silent.
_RELATION_KNOBS: dict[str, Callable[[SnakeQuery[Maker]], SnakeQuery[Maker]]] = {
    "_includes": lambda q: q.include(Maker.nation),
    "_prefetches": lambda q: q.include(Maker.trucks),
}


# How each knob is SPELLED in the refusal. Asserting the spelling and not just the exception type
# is what `test_messages_are_asserted` asks of this repo, and it is the half with any value: the
# message has to name the knob YOU set, not recite all ten.
_SPELLING = {
    "_order": "order_by",
    "_limit": "limit",
    "_offset": "offset",
    "_group_by": "group_by",
    "_having": "having",
    "_distinct": "distinct",
    "_lock": "for_update",
    "_columns": r"only\(\)/defer\(\)",
}


def _filtered() -> SnakeQuery[_User]:
    """A query with a WHERE, so the guard under test is the knob one and not the missing-filter one."""
    return SnakeQuery(_User).filter(_User.name == "ana")


def test_this_file_knows_every_knob_the_query_has() -> None:
    """The parametrisation covers every slot that is a knob. It is the floor under the rest.

    Without it, an eleventh knob added to `SnakeQuery` would be guarded by the derivation and
    untested by this file, and nothing here would go red — which is the same failure mode as the
    hand-written `or` chain, moved one level out.
    """
    knobs = {slot for slot in SnakeQuery.__slots__ if slot not in _NOT_A_KNOB}

    assert knobs == set(_KNOBS) | set(_RELATION_KNOBS), (
        "a knob exists that this file does not exercise"
    )


@pytest.mark.parametrize("slot", sorted(_KNOBS))
def test_a_bulk_write_refuses_every_knob_it_does_not_emit(slot: str) -> None:
    """One case per knob. Four of these were emitting a plain DELETE and saying nothing."""
    query = _KNOBS[slot](_filtered())
    spelling = _SPELLING[slot]

    with pytest.raises(SnakeUnsupportedFeature, match=spelling):
        query.to_delete_sql(_DIALECT)


def test_a_knob_set_to_zero_is_still_a_knob_that_was_set() -> None:
    """`limit(0)` and `offset(0)` are legal, falsy, and MUST still be refused.

    This is the test that stops the cure being worse than the disease. A guard derived by
    truthiness reads `limit(0)` as "no limit set", emits `DELETE FROM users WHERE name = $1` and
    destroys every matching row — for a caller who asked for at most zero of them. It is a
    regression that would have been introduced BY the fix, and no other test in this file sees it.
    """
    with pytest.raises(SnakeUnsupportedFeature, match="limit"):
        _filtered().limit(0).to_delete_sql(_DIALECT)

    with pytest.raises(SnakeUnsupportedFeature, match="offset"):
        _filtered().offset(0).to_delete_sql(_DIALECT)


def test_a_bulk_write_with_only_a_filter_still_works() -> None:
    """The floor: a plain filtered bulk write is the whole point and must stay allowed.

    A guard that refused everything would satisfy every test above.
    """
    sql, params = _filtered().to_delete_sql(_DIALECT)

    assert sql.startswith("DELETE FROM")
    assert "WHERE" in sql
    assert list(params) == ["ana"]


def test_the_refusal_names_the_knob_that_was_actually_set() -> None:
    """The message says which one, because "not supported in a bulk write" sends you hunting.

    The hand-written version listed all six spellings in every message whatever you had set, so the
    reader had to work out which of the six was theirs.
    """
    with pytest.raises(SnakeUnsupportedFeature, match="distinct"):
        _filtered().distinct().to_delete_sql(_DIALECT)

    with pytest.raises(SnakeUnsupportedFeature, match="for_update"):
        _filtered().for_update().to_delete_sql(_DIALECT)


@pytest.mark.parametrize("slot", sorted(_RELATION_KNOBS))
def test_a_bulk_write_refuses_the_relation_knobs_too(slot: str) -> None:
    """`include()` fills TWO slots depending on the cardinality, and both have to be refused.

    The hand-written chain named `_includes` and not `_prefetches`, so a to-MANY include —which is
    the one that lands in the other slot— went through a bulk write without a word.
    """
    query = _RELATION_KNOBS[slot](SnakeQuery(Maker).filter(Maker.name == "x"))

    with pytest.raises(SnakeUnsupportedFeature, match="include|prefetch"):
        query.to_delete_sql(_DIALECT)
