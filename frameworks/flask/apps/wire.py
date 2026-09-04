"""Reading a JSON request body as what it is: untyped data that arrived over the wire.

A request body is not typed and cannot be. It is whatever the client sent, parsed by a parser that
promises nothing about its shape, so every value that comes out of it starts life as `object` and
becomes a `str`, an `int` or a `bool` only where this module says so — once, out loud, at the edge.

That is the whole point of the module. Flask types `request.get_json()` as `Any`, and `Any` does not
mean "unknown" to a type-checker: it means "stop checking". Every call site downstream went quiet,
not because it was right but because nothing was looking, and the endpoints of this demo type-checked
green over values nobody had verified. Handing `Any` to a gate and reading its Success is the one
failure this repository refuses to buy.

So the body is a `Mapping[str, object]`, and the conversions are named. The call site says which type
it expects and what it does when the client did not send it, and the checker verifies the rest.

Each converter mirrors what the demo already did inline (`int(...)`, `str(...)`, `bool(...)`), with
one deliberate improvement: a `null` in the JSON falls back to the default instead of becoming the
string `"None"` or blowing up on `int(None)`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from flask import Request

_EMPTY: Mapping[str, object] = {}


def json_object(request: Request) -> Mapping[str, object]:
    """The request body when it is a JSON object, or an empty mapping when it is anything else.

    `silent=True` keeps the old behaviour of these endpoints: a body that is not JSON at all is an
    empty object, not a 400 raised by the parser, so the use case is the one that decides what a
    missing field means. A client that posts an array or a bare scalar lands in the same place.
    """
    data: object = request.get_json(silent=True)
    if isinstance(data, Mapping):
        return {str(key): value for key, value in data.items()}
    return _EMPTY


def text(value: object, default: str = "") -> str:
    """The value as text; the default when the key was absent or its value was `null`."""
    if value is None:
        return default
    return str(value)


def optional_text(value: object) -> str | None:
    """The value as text, or `None` when the key was absent — the two are the same answer here."""
    if value is None:
        return None
    return str(value)


def integer(value: object, default: int = 0) -> int:
    """The value as a whole number; the default when it was absent or `null`.

    A numeric string converts, exactly as `int("3")` did before this module existed; anything else
    raises, because a body that says `{"units": {"a": 1}}` is a client bug and hiding it behind a
    zero would silently ship the wrong quantity.
    """
    if value is None:
        return default
    if isinstance(value, bool | int | float | str):
        return int(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


def optional_integer(value: object) -> int | None:
    """The value as a whole number, or `None` when the key was absent — and `None` MEANS something.

    The `integer` above answers a default for an absent key, which is right where the field is
    required and merely unwritten. Here the absence is the answer: a tag with no `parent_id` is a
    ROOT of the taxonomy, and defaulting it to zero would point it at a row that does not exist.

    An empty STRING is absent too, and that is not leniency: it is what the empty option of a
    `<select>` posts, so the form and the JSON body reach this with the same meaning.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool | int | float | str):
        return int(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


def real(value: object, default: float = 0.0) -> float:
    """The value as a floating-point number; the default when it was absent or `null`."""
    if value is None:
        return default
    if isinstance(value, bool | int | float | str):
        return float(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


def flag(value: object, default: bool = False) -> bool:
    """The value as a boolean; the default when it was absent or `null`."""
    if value is None:
        return default
    return bool(value)


def optional_flag(value: object) -> bool | None:
    """The value as a boolean, or `None` when the key was absent.

    The distinction is load-bearing for a partial update: "do not touch `published`" and "set
    `published` to false" are different requests, and only `None` can carry the first one.
    """
    if value is None:
        return None
    return bool(value)


def mapping(value: object) -> Mapping[str, object]:
    """The value as a nested JSON object, or an empty one when it is not one."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return _EMPTY


def sequence(value: object) -> Sequence[object]:
    """The value as a JSON array, or an empty one when it is not one.

    `str` and `bytes` are sequences to Python and are NOT arrays here: letting `"abc"` through would
    iterate three characters where the caller asked for three elements.
    """
    if isinstance(value, str | bytes):
        return ()
    if isinstance(value, Sequence):
        return value
    return ()


def integer_pairs(value: object) -> list[tuple[int, int]]:
    """A JSON array of two-number arrays, as pairs. Anything that is not a pair is dropped.

    This is the shape an order's lines arrive in — `[[sku_id, quantity], ...]` — and unpacking it
    needs the two halves to be numbers before the tuple exists, not after.
    """
    pairs: list[tuple[int, int]] = []
    for item in sequence(value):
        parts = sequence(item)
        if len(parts) == 2:
            pairs.append((integer(parts[0]), integer(parts[1])))
    return pairs
