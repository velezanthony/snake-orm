"""`__repr__`, `__eq__` and `__hash__` of the models.

An ORM that advertises itself as **dataclass-first** and whose `print(user)` gave back
`<User object at 0x7f...>`. `_make_init` installed the `__init__` and nothing else.

Equality goes by the PK read off the GRAPH (`SnakePrimaryKeyInfo.columns`), not by a magic `pk`
attribute like Django's. That difference is not cosmetic: Django's `pk` is an alias invented on top
of the real field, and that is why composite PKs cost it until 5.2. Here the graph already knows
which columns are the key, so the composite one comes out of the SAME code.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
)


@snake_model(table="req_users")
class ReqUser(SnakeModel):
    """User with a simple autoincrement PK."""

    id: SnakeColumn[int] = snake_auto()
    email: SnakeColumn[str] = snake_str()


@snake_model(table="req_lines")
class ReqLine(SnakeModel):
    """Order line with a COMPOSITE PK: the case Django struggles with."""

    order_id: SnakeColumn[int] = snake_int(primary_key=True)
    position: SnakeColumn[int] = snake_int(primary_key=True)
    quantity: SnakeColumn[int] = snake_int()


def test_repr_shows_the_columns_in_graph_order() -> None:
    """The repr is READABLE and ordered like the graph: it is for debugging, not decoration."""
    line = ReqLine(order_id=7, position=1, quantity=3)
    assert repr(line) == "ReqLine(order_id=7, position=1, quantity=3)"


def test_repr_quotes_strings_so_the_value_is_unambiguous() -> None:
    """A text value looks like text: `email='a@x.com'`, never `email=a@x.com`."""
    user = ReqUser(email="a@x.com")
    user.id = 1  # the id is put there by the INSERT; here it is simulated
    assert repr(user) == "ReqUser(id=1, email='a@x.com')"


def test_repr_survives_a_column_that_is_not_set_yet() -> None:
    """A half-built object is STILL printable.

    Right before the INSERT the id is not set yet, and that is THE moment you want to print it. A
    repr that blows up there is worse than having no repr at all.
    """
    user = ReqUser(email="a@x.com")
    assert "ReqUser(" in repr(user)
    assert "<unassigned>" in repr(user)


def test_two_rows_with_the_same_pk_are_equal() -> None:
    """What is really expected: two objects of the SAME row are equal."""
    first, second = ReqUser(email="a@x.com"), ReqUser(email="other@x.com")
    first.id = second.id = 7
    assert first == second, "a row's identity is its PK, not its other columns"


def test_a_composite_primary_key_needs_no_special_case() -> None:
    """The COMPOSITE PK works off the same code: the graph already knows which columns it is."""
    first = ReqLine(order_id=7, position=1, quantity=3)
    same = ReqLine(order_id=7, position=1, quantity=99)
    other = ReqLine(order_id=7, position=2, quantity=3)

    assert first == same
    assert first != other


def test_models_of_different_classes_are_never_equal() -> None:
    """The class counts: two different tables holding id 7 are not the same row."""
    user = ReqUser(email="a@x.com")
    user.id = 7
    line = ReqLine(order_id=7, position=7, quantity=1)
    assert user != line


def test_instances_without_a_pk_fall_back_to_identity() -> None:
    """Two objects NOT inserted yet are never mistaken for each other.

    With no PK there is no row identity to compare. Calling them equal would merge two distinct new
    records inside a `set` and lose one of them.
    """
    first, second = ReqUser(email="a@x.com"), ReqUser(email="a@x.com")
    assert first != second
    assert first == first


def test_equal_instances_hash_the_same() -> None:
    """Python's own contract: if two objects are equal, their hash matches."""
    first, second = ReqUser(email="a@x.com"), ReqUser(email="other@x.com")
    first.id = second.id = 7

    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_hashing_an_instance_without_a_pk_is_refused() -> None:
    """THE DJANGO BUG, dodged: with no PK the object is NOT hashable, and it says why.

    Were hashing allowed, putting it into a `set` before the INSERT and letting the INSERT fill in
    the id would MUTATE its hash inside the set, and from then on the object is unrecoverable from
    that collection. Forbidding it costs one clear exception; allowing it costs an afternoon of
    debugging.
    """
    with pytest.raises(TypeError, match="is not hashable until it has a primary key"):
        hash(ReqUser(email="a@x.com"))
