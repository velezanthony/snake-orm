"""A relationship names ONE model, and saying otherwise is refused with a message instead of a crash.

This guard is not a nicety: it is what makes the typing of `SnakeToOne.__get__` SOUND.

Class access on a to-one unwraps the `| None` through an overload on the type of `self`
(`self: SnakeToOne[N | None]` -> `type[N]`), which is what lets `Post.editor.username` be written
across a nullable key. That overload has one hole, and it is measured: with a union of TWO models
plus `| None` the two checkers disagree — mypy infers `type[Never]` and pyright infers
`type[Card] | type[Transfer]`. `type[Never]` is not an error, it is a TYPE, so mypy would go green
over a line that means nothing and the project's two gates would answer differently about it.

The hole is closed by making the case UNREACHABLE rather than by patching the signature: a
relationship whose target is a union of models is refused at link time, so no model can ever hand
that shape to the descriptor. See `SnakeToOne.__get__`, whose docstring names this file.

What the guard replaced was not a rejection, it was a FALL:

    AttributeError: 'types.UnionType' object has no attribute '__name__'. Did you mean: '__ne__'?

raised from the linker's own guts while formatting an unrelated error message. It did not say what
had been done wrong, did not name the relationship, and suggested `__ne__`.

And the `Card | Transfer | None` case — union AND optional, the exact shape that breaks the
signature — did not even crash: `unwrap_optional` returns the FIRST non-None member, so the ORM
silently resolved the relationship to `Card` and threw `Transfer` away. A crossed foreign key with
no error anywhere, which is worse than the fall.
"""

# WITHOUT `from __future__ import annotations` on purpose: the models are declared INSIDE each test
# (every scenario needs its own registry), and with deferred annotations `get_type_hints` would
# resolve them against the module globals, where a local class does not exist.

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.registry import SnakeRegistry


@pytest.fixture
def reg() -> SnakeRegistry:
    """A registry of its own: linking is per registry and these tests declare broken models."""
    return SnakeRegistry()


def test_a_to_one_onto_a_union_of_models_is_refused(reg: SnakeRegistry) -> None:
    """`SnakeToOne[Card | Transfer]` is rejected at link time, naming what to do instead.

    This is the case that used to fall over with an `AttributeError` about `__name__`. The assert is
    on the CONTENT of the message and not merely on the exception type, because the whole point of
    the change is that the reader is told which relationship is wrong and what to write instead.
    """

    @snake_model(table="cards", registry=reg)
    class Card(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="transfers", registry=reg)
    class Transfer(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="orders", registry=reg)
    class Order(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        payment_id: SnakeColumn[int] = snake_int()
        payment: SnakeToOne[Card | Transfer] = snake_to_one(payment_id)

    with pytest.raises(SnakeRegistryError) as caught:
        snake_link(reg)

    message = str(caught.value)
    assert "Order.payment" in message, (
        "the message must name the offending relationship"
    )
    assert "Card" in message and "Transfer" in message, (
        "it must name the union it was handed"
    )
    assert "one model" in message, "it must say a relationship points at ONE model"
    assert "base" in message.lower(), (
        "it must point at the base-class route for a hierarchy"
    )


def test_a_to_one_onto_a_union_of_models_that_is_also_optional_is_refused(
    reg: SnakeRegistry,
) -> None:
    """`SnakeToOne[Card | Transfer | None]`: the case that broke the signature AND stayed silent.

    Two things had to be true at once for this to be dangerous, and they were. The descriptor's
    overload on `self` infers `type[Never]` here under mypy, so the checker approves the line; and
    the linker's `unwrap_optional` returns the first non-None member, so the relationship resolved
    to `Card` alone with `Transfer` dropped and no error raised at any layer.

    Separate test rather than a parametrise case because it fails for a DIFFERENT reason than the
    one above — silence rather than a crash — and a shared body would hide that.
    """

    @snake_model(table="cards", registry=reg)
    class Card(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="transfers", registry=reg)
    class Transfer(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="orders", registry=reg)
    class Order(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        payment_id: SnakeColumn[int | None] = snake_int()
        payment: SnakeToOne[Card | Transfer | None] = snake_to_one(payment_id)

    with pytest.raises(SnakeRegistryError) as caught:
        snake_link(reg)

    message = str(caught.value)
    assert "Order.payment" in message
    assert "Card" in message and "Transfer" in message, (
        "the dropped member must be named: resolving to `Card` in silence is the bug"
    )


def test_a_to_many_onto_an_optional_child_is_refused(reg: SnakeRegistry) -> None:
    """`SnakeToMany[Comment | None]` is refused: a collection is never absent, it is empty.

    A to-one's `| None` means something real (the foreign key may be NULL). A to-many's does not: a
    parent with no children is handed `[]`, never `None`, and instance access is typed `list[M]` —
    so `SnakeToMany[Comment | None]` would be claiming a list that may hold `None`s, which no code
    path in the ORM can produce.

    It is refused rather than quietly unwrapped for the reason this whole file exists: the to-many
    branch of the linker never called `unwrap_optional` at all, so this annotation fell over with
    the same `AttributeError` about `__name__`.

    The models come from a module of their own rather than from this function body because the two
    reference each other, so one annotation is always a forward reference and `get_type_hints`
    resolves those against module globals. Declared locally, this failed with a `NameError` — a red
    that says nothing about the guard.
    """
    from test.linker import to_many_optional

    with pytest.raises(SnakeRegistryError) as caught:
        snake_link(to_many_optional.reg)

    message = str(caught.value)
    assert "Post.comments" in message
    assert "empty" in message.lower(), (
        "it must say a collection comes back EMPTY rather than absent"
    )


def test_an_optional_to_one_still_links(reg: SnakeRegistry) -> None:
    """The control, and it guards against the guard.

    `SnakeToOne[Brand | None]` is the supported way of saying a key may be NULL, and it must go on
    working untouched. A guard that also swallowed this would have taken the ORM's nullable
    relationships with it — and the tests above would still have passed, which is exactly how a
    guard that covers too much stays invisible.
    """

    @snake_model(table="brands", registry=reg)
    class Brand(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        name: SnakeColumn[str] = snake_str()

    @snake_model(table="cars", registry=reg)
    class Car(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        brand_id: SnakeColumn[int | None] = snake_int()
        brand: SnakeToOne[Brand | None] = snake_to_one(brand_id)

    snake_link(reg)

    table = reg.table_of(Car)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "brand")
    assert relation.target == "Brand"
