"""The registry for the SECOND axis of the type vocabulary: how a value TRAVELS there and back.

The type vocabulary has two axes, and until now only one of them was open:

- **How the column is WRITTEN** — `dialect.register_type(type, sql)`. It goes per dialect, because
  the same Python type is written `INET` in Postgres and `TEXT` in SQLite.
- **How the value TRAVELS** — this. It goes global, and it can go global because `from_db` is
  IDEMPOTENT.

That idempotence is the piece the whole design rests on. The eleven internal converters already
honour it: `_to_decimal` swallows the `Decimal` Postgres returns and the `str` SQLite returns with
the same code, so nobody has to ask which engine they are on. Without it we would have to register
one converter per engine, and the value axis would stop being agnostic.

It lives in `core/` because both ends of the journey consult it: `sql/adapt.py` on write and
`session/coercion.py` on read. Anywhere else would create a cycle between `sql/` and `session/`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar, cast

from snakeorm.core.exceptions import SnakeConfigError

T = TypeVar("T")

ToDb = Callable[[object], object]
"""From the domain type to something a DBAPI driver knows how to send, as it is STORED in the
registry.

Converters come in typed —`register_converter` is generic in the type being declared, so whoever
writes the `to_db` receives their own type and not `object`— and are stored untyped because the
registry is heterogeneous: a single table with a different type per key.
"""

FromDb = Callable[[object], object]
"""From what the driver returns to the domain type. It MUST be idempotent. See `ToDb`."""

_TO_DB: dict[type, ToDb] = {}
_FROM_DB: dict[type, FromDb] = {}

_BUILTIN: set[type] = set()
"""The types whose journey the ORM already defines. `session/coercion.py` DECLARES them on import.

The direction matters: `core/` cannot import `session/` —`test_layering` checks it, and rightly so:
a cycle between layers turns import order into part of the behaviour—. So the upper layer registers
itself when it loads, instead of this one going off to ask it.
"""

_PROBES: tuple[object, ...] = ("", 0, b"")
"""The values idempotence is tested with at registration time.

They do not aim to cover the type's domain: all it takes is ONE round the converter knows how to
make, so we can make it again and compare. If it can make none of them, the check keeps quiet —
testing with what the converter does not accept would claim it is not idempotent when something else
is going on.
"""


def register_converter(
    python_type: type[T],
    *,
    to_db: Callable[[T], object],
    from_db: Callable[[object], T],
) -> None:
    """Declares how a domain type travels: from Python to the driver and back.

    Generic in the declared type, so whoever writes the converters works with THEIR type and not
    with `object`: `to_db` receives an `Inet` and `from_db` returns an `Inet`, and the checker
    verifies it. An ORM whose selling point is typing cannot ask for untyped lambdas in its own API.

    `from_db` MUST be idempotent —`from_db(from_db(x)) == from_db(x)`— because the same converter
    serves all three engines and each returns the column in one shape: Postgres may hand over the
    object already and SQLite the text. It is checked here, at registration time, and not on the
    first read in production.

    It does not rewrite the types the ORM already handles. A global registry is an invitation for a
    third-party library to change how a `Decimal` travels for the entire process just by being
    imported.
    """
    if python_type in _BUILTIN:
        raise SnakeConfigError(
            f"{python_type!r} is a type the ORM already handles, so its converter is not rewritten. "
            f"A global registry is shared by the whole process: changing here how a core type "
            f"travels would change it too for code that asked for nothing."
        )
    _demand_idempotent(python_type, from_db)
    # The registry is heterogeneous (one key per type, each with its own signature), so they are
    # stored untyped. The `cast` loses nothing: the generic signature already checked the pair at
    # the call site.
    _TO_DB[python_type] = cast("ToDb", to_db)
    _FROM_DB[python_type] = cast("FromDb", from_db)


def _demand_idempotent(python_type: type, from_db: Callable[[object], object]) -> None:
    """Checks that applying `from_db` twice gives the same as applying it once.

    It is tested with probe values, ignoring the ones the converter cannot swallow: what we are
    after is a round it CAN make, so we can make it again. If no probe works, nothing is claimed —
    a false positive here would block a perfectly correct type.

    The two calls are attempted SEPARATELY, and that separation is the whole guard rather than a
    tidying-up. Under a single `try` both failures looked the same and both were read as "this probe
    does not fit the type, try the next one" — but they are opposite facts. The FIRST call failing
    says nothing about the converter: the probe simply is not of its shape. The SECOND call failing
    says everything: the converter swallowed a value and then choked on the value it had just
    produced, which is exactly what happens the day the engine underneath hands back the object
    already built instead of its text. So the more dangerous of the two ways of not being idempotent
    was the one that registered without a word, and it surfaces on a READ, in production, over rows
    that are already written.
    """
    for probe in _PROBES:
        try:
            once = from_db(probe)
        except Exception:  # noqa: BLE001 - the probe does not fit this type; try the next one
            continue
        try:
            twice = from_db(once)
        except Exception as error:
            raise SnakeConfigError(
                f"The `from_db` of {python_type!r} is not idempotent: it accepted {probe!r} and "
                f"then failed on the value it had just returned ({error!r}). It has to accept its "
                f"own output, because the same converter reads from the three engines and each one "
                f"returns the column in a different shape: one may hand over the object already and "
                f"another the text. Make it return the value as it is when it already is the "
                f"expected type."
            ) from error
        if once != twice:
            raise SnakeConfigError(
                f"The `from_db` of {python_type!r} is not idempotent: converting twice gives "
                f"something different from converting once ({once!r} and then {twice!r}). It has to be, "
                f"because the same converter reads from the three engines, and each one returns the "
                f"column in a different shape: one may hand over the object already and another the "
                f"text. Make it return the value as it is when it already is the expected type."
            )
        return


def mark_builtin(types: Iterable[object]) -> None:
    """Declares which types the ORM already handles, so `register_converter` will not rewrite them.

    `session/coercion.py` calls it on import, with the keys of its own registry: that way the list
    is not duplicated —nor can it drift— and `core/` still imports nobody from above.
    """
    _BUILTIN.update(klass for klass in types if isinstance(klass, type))


def to_db_for(value: object) -> ToDb | None:
    """The adapter for a VALUE, looked up by its type and its bases', or `None` if there is none.

    By MRO and not by exact `type(value)` so a subclass of the registered type inherits the journey,
    which is what anyone declaring `class IPv4(Inet)` expects.
    """
    if not _TO_DB:
        return None
    for klass in type(value).__mro__:
        adapter = _TO_DB.get(klass)
        if adapter is not None:
            return adapter
    return None


def from_db_for(python_type: object) -> FromDb | None:
    """The read converter of a DECLARED type, or `None` if none was registered."""
    if not isinstance(python_type, type):
        return None
    for klass in python_type.__mro__:
        converter = _FROM_DB.get(klass)
        if converter is not None:
            return converter
    return None
