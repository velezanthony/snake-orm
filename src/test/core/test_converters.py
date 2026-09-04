"""The converter registry itself: what it accepts, what it refuses, and with which words.

`src/test/dialects/test_register_converter.py` already covers the two axes MEETING — a type declared
with `register_type` plus `register_converter` written on one engine and read on another. This file
looks at the other half, the registry on its own, because that is where the guard lives: a
`register_converter` that accepts a converter it should have refused does not fail on registration,
it fails months later on a READ, and by then the wrong value is already in the rows.

The messages are asserted WHOLE, not by a fragment. In an ORM whose doctrine is to shout instead of
guessing, the message is the product: it is the only thing between whoever wrote a bad converter and
finding out on production data. `match="is not idempotent"` proves an exception was raised; it does
not prove the sentence that explains what to do about it still exists.
"""

from __future__ import annotations

import pathlib
import re
import sys
import types
from collections.abc import Iterator
from decimal import Decimal

import pytest

from snakeorm.core import converters
from snakeorm.core.converters import from_db_for, register_converter, to_db_for
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.registry import registry


class Inet:
    """An IP address from the user's domain: a type the ORM has never heard of."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        """Two equal addresses are the same address; needed to assert the round trip."""
        return isinstance(other, Inet) and other.value == self.value

    def __hash__(self) -> int:
        """Declared next to `__eq__`, so the type is not left without a hash."""
        return hash(self.value)

    def __repr__(self) -> str:
        """A STABLE repr, and that is what makes the whole message assertable.

        The complaint about idempotence quotes the two values it compared, so with the default repr
        the sentence carries a memory address and can only be matched by fragments — which is how a
        message drifts sentence by sentence while its test stays green.
        """
        return f"Inet({self.value!r})"


class Ipv4(Inet):
    """A narrower `Inet`. It exists to check that the journey is inherited down the MRO."""


class Strict:
    """A domain type whose constructor REFUSES anything that is not a `str`.

    It is the counterexample the idempotence guard is for, and it is deliberately stricter than
    `Inet`: handed its own output it does not nest quietly, it raises. Both are broken converters;
    only one of the two used to be caught.
    """

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"Strict takes a str, not {type(value).__name__}")
        self.value = value


def _swallows_nothing(raw: object) -> object:
    """A `from_db` that refuses every probe, so the guard has no round to measure.

    Its type is declared as accepting `object` and it accepts none: the registry has no way to tell
    an unfit probe from a converter that is simply narrow, and this is what that looks like.
    """
    raise ValueError(f"no probe fits: {raw!r}")


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Leaves the global tables exactly as they were found: the two journeys and the models.

    The value axis is GLOBAL on purpose — a domain type travels the same way whatever engine it goes
    to — and a global table means a test that registers something hands it to every test that runs
    afterwards. Restoring is cheaper than diagnosing that three weeks from now somewhere unrelated.

    The MODEL registry goes with them because of one test only: the one running the guide's example,
    which declares a `Server` on a table called `servers`. It is a singleton too, and a stray model
    in it is the kind of collision that only shows up in the full suite and vanishes when the file
    runs alone.
    """
    to_db = converters._TO_DB.copy()
    from_db = converters._FROM_DB.copy()
    models = {name: store.copy() for name, store in vars(registry).items()}
    yield
    converters._TO_DB.clear()
    converters._TO_DB.update(to_db)
    converters._FROM_DB.clear()
    converters._FROM_DB.update(from_db)
    for name, store in vars(registry).items():
        store.clear()
        store.update(models[name])


def _idempotent(raw: object) -> Inet:
    """The `from_db` the guide teaches: it swallows the object AND the text with the same code."""
    return raw if isinstance(raw, Inet) else Inet(str(raw))


def test_a_registered_type_survives_the_round_trip() -> None:
    """Verifies the happy path: a domain type goes out through `to_db` and comes back its own again.

    It is asserted over the registry's own two lookups rather than over a session, because that is
    the contract `sql/adapt.py` and `session/coercion.py` consume: whatever those two ask for, this
    is what they get.
    """
    register_converter(Inet, to_db=lambda ip: ip.value, from_db=_idempotent)

    write = to_db_for(Inet("10.0.0.1"))
    read = from_db_for(Inet)
    assert write is not None
    assert read is not None
    assert write(Inet("10.0.0.1")) == "10.0.0.1"
    assert read("10.0.0.1") == Inet("10.0.0.1")
    assert read(write(Inet("10.0.0.1"))) == Inet("10.0.0.1")


def test_a_subclass_inherits_the_journey_of_its_base() -> None:
    """Verifies the MRO lookup the column guide promises for `class IPv4(Inet)`.

    Both directions are asserted, and the second is the one that would rot unnoticed: writing looks
    the VALUE up by `type(value).__mro__` and reading looks the DECLARED type up the same way. A
    lookup by exact `type()` would pass the first assertion and fail the pair.
    """
    register_converter(Inet, to_db=lambda ip: ip.value, from_db=_idempotent)

    write = to_db_for(Ipv4("192.168.1.1"))
    read = from_db_for(Ipv4)
    assert write is not None, "a subclass of a registered type writes like its base"
    assert read is not None, "and reads like it too"
    assert write(Ipv4("192.168.1.1")) == "192.168.1.1"


def test_an_undeclared_type_has_no_journey_at_all() -> None:
    """Verifies that the registry answers `None` rather than guessing, for a type nobody declared.

    `None` is what lets the layers above fall back to what they already knew how to do. Anything
    invented here would be a value silently reshaped on its way into the database.
    """
    assert to_db_for(Inet("10.0.0.1")) is None
    assert from_db_for(Inet) is None
    assert from_db_for("not a type at all") is None


def test_a_reader_that_nests_is_refused_with_the_whole_message() -> None:
    """Verifies the classic non-idempotent converter is refused, and asserts the message ENTIRE.

    The counterexample is the one everybody writes — handing the guard the type's own constructor —
    and it deserves a message rather than a bare exception because `Inet(Inet("10.0.0.1"))` does not
    fail: it NESTS, and the nesting only shows up when the value is compared or serialized, far away
    from the line that caused it. The message is what carries that explanation, so it is what gets
    asserted.
    """
    # The `type: ignore` reproduces the nesting on purpose: mypy sees that `Inet` does not take an
    # `Inet`, which is precisely the mistake being described, and the message quotes both values.
    nested = Inet(Inet(""))  # type: ignore[arg-type]
    expected = (
        f"The `from_db` of {Inet!r} is not idempotent: converting twice gives something different "
        f"from converting once ({Inet('')!r} and then {nested!r}). It has to be, because "
        f"the same converter reads from the three engines, and each one returns the column in a "
        f"different shape: one may hand over the object already and another the text. Make it "
        f"return the value as it is when it already is the expected type."
    )

    with pytest.raises(SnakeConfigError) as complaint:
        # The `type: ignore` is part of the test: mypy ALREADY sees that `Inet` does not fit the
        # `from_db` signature. A checker catching half the cases does not remove the runtime guard —
        # an untyped `lambda` gets here just the same.
        register_converter(Inet, to_db=lambda ip: ip.value, from_db=Inet)  # type: ignore[arg-type]

    assert str(complaint.value) == expected
    assert from_db_for(Inet) is None, "a refused converter must not be half-registered"
    assert to_db_for(Inet("10.0.0.1")) is None, "nor may its `to_db` be left behind"


def test_a_reader_that_blows_up_on_its_own_output_is_refused_too() -> None:
    """Verifies the OTHER way of not being idempotent: the second application raises.

    This is the case the guard used to wave through, and it is the more dangerous of the two. The
    loop caught every exception in one `try` and read it as "this probe does not fit the type, try
    the next one" — but a `from_db` that swallowed the probe and then choked on its OWN output is not
    a bad probe, it is precisely the converter that will blow up the day the engine underneath
    returns the object already built. Which is a READ, in production, on data that is already there.

    The two situations are told apart by WHICH of the two calls failed, and nothing else can tell
    them apart: the first application failing means the probe is unfit, the second failing means the
    converter is.
    """
    with pytest.raises(SnakeConfigError) as complaint:
        register_converter(Strict, to_db=lambda s: s.value, from_db=Strict)  # type: ignore[arg-type]

    assert "is not idempotent" in str(complaint.value)
    assert "Strict takes a str, not Strict" in str(complaint.value), (
        "the message has to carry what the second conversion actually complained about, "
        "or whoever reads it learns nothing about their own converter"
    )
    assert from_db_for(Strict) is None


def test_a_reader_no_probe_fits_is_taken_on_trust_and_that_is_declared() -> None:
    """Verifies the guard stays QUIET when it could not measure a single round, on purpose.

    It is the deliberate hole and it is written down rather than hidden: the probes (`""`, `0`,
    `b""`) do not try to cover the domain of every type anybody might declare, so a converter that
    accepts none of them has not been proven non-idempotent — it has not been proven anything.
    Refusing it would block a perfectly correct type on no evidence, which is worse than the risk of
    letting an unmeasurable one through.

    Whoever widens `_PROBES` some day is looking at the test that says what the silence means.
    """
    register_converter(Inet, to_db=lambda ip: ip.value, from_db=_swallows_nothing)  # type: ignore[arg-type]

    assert from_db_for(Inet) is not None, "unmeasurable is not the same as refused"


def test_a_type_the_orm_already_handles_is_refused_with_the_whole_message() -> None:
    """Verifies the built-in journeys are not rewritable, asserting the message the guide prints.

    The message is quoted verbatim in `docs/users/guide/columns.md` inside a ```text block, so it is
    a FACT and not prose: what is asserted here is the same sentence a reader was promised. It also
    has to explain the reason, because from where the caller sits, refusing looks arbitrary — the
    registry is global, and a third-party library changing how a `Decimal` travels would change it
    for a whole process that asked for nothing.
    """
    expected = (
        f"{Decimal!r} is a type the ORM already handles, so its converter is not rewritten. "
        f"A global registry is shared by the whole process: changing here how a core type travels "
        f"would change it too for code that asked for nothing."
    )

    with pytest.raises(SnakeConfigError) as complaint:
        register_converter(Decimal, to_db=str, from_db=lambda raw: Decimal(str(raw)))

    assert str(complaint.value) == expected


def test_registering_the_same_type_twice_replaces_its_journey() -> None:
    """Verifies what a SECOND registration of the same type does: the last one wins, in silence.

    Written down because it is a decision, not an accident, and because it is the opposite of the
    rule right above it: a built-in type cannot be rewritten at all, a type of your own can be
    rewritten as often as you like. The asymmetry is deliberate — the ORM defends what IT declared,
    and does not police what the user declared about their own types, where re-registering is what
    happens naturally when a module is reloaded or a test re-runs.

    The cost is real and belongs in the record: two libraries declaring the same domain type resolve
    it by import order, quietly. Should that ever become a shout, this is the test that has to change
    first, and its name says which behaviour was traded away.
    """
    register_converter(Inet, to_db=lambda ip: ip.value, from_db=_idempotent)
    register_converter(
        Inet,
        to_db=lambda ip: f"inet:{ip.value}",
        from_db=lambda raw: (
            raw if isinstance(raw, Inet) else Inet(str(raw).removeprefix("inet:"))
        ),
    )

    write = to_db_for(Inet("10.0.0.1"))
    read = from_db_for(Inet)
    assert write is not None
    assert read is not None
    assert write(Inet("10.0.0.1")) == "inet:10.0.0.1"
    assert read("inet:10.0.0.1") == Inet("10.0.0.1")


def _published_example() -> str:
    """The block of `guide/columns.md` that teaches `register_converter`, as published.

    It is read from the page instead of being copied here, and that is the whole value of this test:
    a copy would go on passing the day the page changed, which is the exact failure this repository's
    documentation nets exist to prevent. The block is located by what it TEACHES rather than by its
    number, so inserting a section above it does not silently point this at something else.
    """
    page = (
        pathlib.Path(__file__).resolve().parents[3]
        / "docs"
        / "users"
        / "guide"
        / "columns.md"
    )
    blocks = [
        found.group("body")
        for found in re.finditer(
            r"^```python\n(?P<body>.*?)^```", page.read_text(), re.MULTILINE | re.DOTALL
        )
        if "register_converter(" in found.group("body")
    ]
    assert len(blocks) == 1, (
        f"expected exactly one published example of `register_converter` in {page.name}, "
        f"found {len(blocks)}"
    )
    return blocks[0]


def test_the_published_example_works_exactly_as_written() -> None:
    """Verifies the guide's `Inet` example runs, and that its value really makes the round trip.

    `test_docs.py` already executes this block, so it proves it does not blow up. That is not the
    same as proving it WORKS: the example's whole point is the `if isinstance` inside `from_db`, and
    a block that merely runs says nothing about whether the value comes back the type it left as.
    The two nets sit at different heights on purpose.
    """
    # A real module and not a bare `dict`: the example declares a model, and the compiler resolves
    # its annotations with `get_type_hints`, which looks them up in the module the class says it
    # belongs to. A class born inside an `exec` over a loose dictionary belongs to none, and every
    # annotation comes back `NameError`. Same lesson as in `test_docs.py`.
    module = types.ModuleType("snakeorm_columns_guide_example")
    sys.modules[module.__name__] = module
    try:
        exec(compile(_published_example(), "<columns.md>", "exec"), module.__dict__)  # noqa: S102
    finally:
        del sys.modules[module.__name__]

    inet = module.__dict__["Inet"]
    assert isinstance(inet, type)
    address = inet("10.0.0.1")

    write = to_db_for(address)
    read = from_db_for(inet)
    assert write is not None, "the example's `to_db` did not reach the registry"
    assert read is not None, "nor did its `from_db`"

    sent = write(address)
    assert sent == "10.0.0.1", (
        "the driver has to receive text, not an object it cannot send"
    )
    back = read(sent)
    assert isinstance(back, inet), (
        "reading has to rebuild the domain type, not leave the text"
    )
    assert read(back) is back, (
        "and reading twice is the idempotence the example is teaching"
    )
