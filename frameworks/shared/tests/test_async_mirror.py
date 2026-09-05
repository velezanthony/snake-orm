"""`shared/aio/` is a MIRROR of `shared/usecases/`, and this is what makes that a fact.

The asynchronous demo needs a second orchestration of every operation, because `await` is syntax and
one function body cannot serve both colours. A second copy of anything is a promise, and a promise
nobody checks is how the lab ended up building its sections twice and the blog its dicts three
times. So the promise is spelled out as three properties and asserted:

- **the same names.** A module under `shared/aio/` covers EVERY public use case of the synchronous
  module it twins. This is the one that matters most: without it, "we made FastAPI async" and "the
  FastAPI demo answers fewer questions than the other two" are the same commit, and nothing says so.
- **the same parameters.** Same names in the same order with the same defaults, so a caller reads
  identically on both paths and a parameter added to one side cannot be forgotten on the other.
- **actually asynchronous.** A twin that is a plain `def` would pass the two checks above and block
  the event loop it was written to free.

What is deliberately NOT asserted is the other direction — that every synchronous use case has an
asynchronous twin. A domain earns a twin by being SERVED asynchronously, not by existing, so a
domain the FastAPI demo does not answer is free to have only one colour. What the first property
pins is that a domain, once twinned, is twinned WHOLE.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib
from types import FunctionType, ModuleType

import pytest

from shared import aio

_AIO = pathlib.Path(aio.__file__).resolve().parent
_DOMAINS = tuple(sorted(aio.public_functions()))


def _module(package: str, domain: str) -> ModuleType:
    """The `<domain>_usecases` module of one of the two layers."""
    return importlib.import_module(f"shared.{package}.{domain}_usecases")


def _public_functions(module: ModuleType) -> dict[str, FunctionType]:
    """The functions DEFINED in a module: an imported helper belongs to whoever defined it."""
    return {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("_")
        and isinstance(value, FunctionType)
        and value.__module__ == module.__name__
    }


def test_there_are_twins_to_compare() -> None:
    """That the discovery found modules at all, which is the trap of every self-discovering check.

    With an empty `_DOMAINS` every parametrised test below vanishes and the suite goes green over
    nothing — the same failure `test_orm_api_coverage.py` guards against with its own probe.
    """
    modules = sorted(path.stem for path in _AIO.glob("*_usecases.py"))

    assert modules, f"no `*_usecases.py` found under {_AIO}"
    assert len(_DOMAINS) == len(modules), (
        f"{len(modules)} asynchronous modules on disk and {len(_DOMAINS)} registered in "
        f"`shared/aio/__init__.py`: one of them was written and never imported, so nothing reaches "
        f"it and no net covers it."
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_the_twin_covers_every_use_case_of_its_domain(domain: str) -> None:
    """Every public use case of the synchronous domain has an asynchronous function of the same name.

    This is the assertion that stops the demo from getting thinner in silence. An endpoint that
    cannot be served asynchronously is a decision worth arguing; an endpoint that just never got a
    twin is an outage nobody notices until somebody opens the page.
    """
    synchronous = set(_public_functions(_module("usecases", domain)))
    asynchronous = set(_public_functions(_module("aio", domain)))

    missing = sorted(synchronous - asynchronous)

    assert missing == [], (
        f"`shared/usecases/{domain}_usecases.py` serves these and `shared/aio/` does not: "
        f"{missing}. Either write the twin or delete the synchronous one — a half-mirrored domain "
        f"is a FastAPI demo that answers fewer questions than the other two without saying so."
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_the_twin_takes_the_same_parameters(domain: str) -> None:
    """Same parameter names, same order, same defaults. Only the session's TYPE changes.

    The annotations are excluded from the comparison for exactly one reason: the first parameter is
    a `SnakeSession` on one side and an `AsyncSession` on the other, and that difference IS the
    twin. Everything else — a `user_id` that became keyword-only, a default that moved — has to
    match, or the same call written against the two layers means two different things.
    """
    synchronous = _public_functions(_module("usecases", domain))
    asynchronous = _public_functions(_module("aio", domain))

    differing = {
        name: (_shape(function), _shape(asynchronous[name]))
        for name, function in synchronous.items()
        if name in asynchronous and _shape(function) != _shape(asynchronous[name])
    }

    assert differing == {}, (
        f"the two colours of {domain} disagree on how they are called: {differing}"
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_the_twin_is_actually_asynchronous(domain: str) -> None:
    """Every function in `shared/aio/` is a coroutine function, not a plain one that reads as async.

    A `def` here would satisfy both checks above and block the event loop, which is the one thing
    this whole layer was written to stop. It is worth an assertion because it is invisible: the
    call sites `await` the result and a synchronous function returning a value would fail loudly —
    but one returning nothing at all would not.
    """
    plain = sorted(
        name
        for name, function in _public_functions(_module("aio", domain)).items()
        if not inspect.iscoroutinefunction(function)
    )

    assert plain == [], (
        f"these live in `shared/aio/` and are not coroutines: {plain}. A blocking call in an "
        f"asynchronous demo stops every OTHER request sharing the loop, not just its own."
    )


def _shape(function: FunctionType) -> tuple[tuple[str, str, str], ...]:
    """How a function is CALLED: each parameter's name, kind and default, with no types."""
    return tuple(
        (parameter.name, str(parameter.kind), _default(parameter.default))
        for parameter in inspect.signature(function).parameters.values()
    )


def _default(value: object) -> str:
    """A default rendered so that two colours of the SAME default compare equal.

    A callable default is written by its qualified NAME and not by `repr`, and that is not leniency
    — `repr` of a function carries its memory address, so two function defaults can never compare
    equal no matter what they are, and a comparison that cannot come out equal is not a comparison.

    It is also the same exclusion this file already makes for the session's type, one level down.
    `settle` takes a `charge` whose default accepts every payment; the synchronous one returns and
    the asynchronous one is awaited, so they are necessarily two different objects with one name and
    one meaning. That difference IS the twin, exactly as `SnakeSession` against `AsyncSession` is.
    What still fails here is what should: a default renamed on one side, or moved to another module.
    """
    qualified_name = getattr(value, "__qualname__", None)
    if not callable(value) or qualified_name is None:
        return repr(value)
    # The module's LAST segment: the two twins are `shared.usecases.orders_usecases` and
    # `shared.aio.orders_usecases`, which agree exactly where they should and still differ if a
    # default is moved to another domain's module.
    module = getattr(value, "__module__", "").rsplit(".", 1)[-1]
    return f"{module}.{qualified_name}"
