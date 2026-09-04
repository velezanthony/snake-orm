"""A relation is NOT assigned: it is loaded with `.include()` or written through its FK.

The bug these close: `SnakeToOne.__set__` stored the object in the internal attribute and did NOT
touch the FK column. Which is to say, this passed the checker, raised nothing, and the `UPDATE` went
out WITHOUT `maker_id`:

    truck.maker = another_maker
    session.update(truck)      # the maker_id stays exactly as it was

A type that blesses a line the runtime ignores is precisely what the project README calls "a type
that lies". It is closed by SHOUTING, not by propagating the FK: propagating it would be magic, and
the doctrine is that the ORM warns and the developer decides.

Loading does write the relation, but through a door of its own (`attach_relationship`), not through the
descriptor: loading and assigning are different things and now they take different paths.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeModelError, SnakeRelationshipNotLoaded
from snakeorm.fields.relationship import attach_relationship
from test.scenarios.deep_domain import Maker, Nation, Truck


def test_assigning_a_to_one_relation_raises() -> None:
    """Assigning a to-one relation raises instead of being ignored in silence."""
    truck = Truck(id=1, model="Actros", maker_id=1)
    maker = Maker(id=1, name="Mercedes", nation_id=1)
    with pytest.raises(SnakeModelError, match="maker_id"):
        truck.maker = maker  # type: ignore[assignment]  # the checker rejects it; here we test the runtime


def test_assigning_a_to_many_relation_raises() -> None:
    """Assigning a to-many collection raises as well."""
    maker = Maker(id=2, name="Scania", nation_id=1)
    with pytest.raises(SnakeModelError, match="include"):
        maker.trucks = []  # type: ignore[assignment]  # same: a runtime contract, not a typing one


def test_the_error_names_the_fk_column_to_write_instead() -> None:
    """The message says WHAT to write, not merely that it is forbidden.

    An error that forbids without offering the alternative leaves the user guessing. The one for a
    to-one must name its real FK column (`maker_id`), which is the one that actually persists.
    """
    truck = Truck(id=2, model="Arocs", maker_id=1)
    with pytest.raises(SnakeModelError) as caught:
        truck.maker = Maker(id=3, name="MAN", nation_id=1)  # type: ignore[assignment]
    message = str(caught.value)
    assert "maker_id" in message
    assert ".include(" in message


def test_loading_still_attaches_the_relation() -> None:
    """The loader CAN hang the relation, through a door of its own.

    Had `attach_relationship` not worked, closing assignment would have broken every `.include()`: the
    loader used to write through the very `__set__` that now raises.
    """
    truck = Truck(id=3, model="Atego", maker_id=7)
    maker = Maker(id=4, name="Volvo", nation_id=2)
    attach_relationship(truck, "maker", maker)
    assert truck.maker is maker


def test_a_relation_never_loaded_still_reports_it() -> None:
    """Closing off the write does not muffle the "not loaded" warning when reading."""
    truck = Truck(id=4, model="Axor", maker_id=3)
    with pytest.raises(SnakeRelationshipNotLoaded, match="include"):
        _ = truck.maker


def test_attach_relation_accepts_a_collection() -> None:
    """The loader's door works just the same for a to-many."""
    nation = Nation(id=1, name="Suecia")
    makers = [
        Maker(id=5, name="Volvo", nation_id=1),
        Maker(id=2, name="Scania", nation_id=1),
    ]
    attach_relationship(nation, "makers", makers)
    assert nation.makers == makers
