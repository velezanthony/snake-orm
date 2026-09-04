"""Tests for the package's PUBLIC API: `from snakeorm import ...`.

`snakeorm/__init__.py` is a facade that RE-EXPORTS with a redundant alias (`X as X`), with no
`__all__`: every name is an identifier (refactor-safe), not a literal, and mypy/pyright/ruff
recognise it as a re-export. The public surface, then, is not a list of strings to maintain in
parallel —it is what actually ended up imported in the module—, so these tests DERIVE it at runtime.

The contract they pin down: the minimum surface for declaring/querying/executing is published, and
NOTHING FOREIGN (stdlib or third party) slips in. That second half is stronger than the old "nothing
outside __all__": it catches a stray `from datetime import datetime as datetime`, which a list of
strings could not see.
"""

from __future__ import annotations

import importlib
import re
import types

import snakeorm
from snakeorm import (
    SnakeColumn,
    snake_auto,
    snake_column,
    snake_decimal,
    snake_int,
    snake_json,
    snake_model,
    snake_str,
    snake_table,
)


# The minimum needed to write a model, query it and execute. If any of this disappears from the
# root package, the library stops being usable without knowing its guts.
_ESSENTIALS = (
    snake_model,
    snake_column,
    snake_auto,
    SnakeColumn,
    snake_table,
    # The four declarators, one per type family. They belong in the bare minimum because without
    # them a column with parameters CANNOT be declared: `snake_column()` no longer takes
    # `max_length`, `int_size`, `precision`/`scale` or `json_storage`. Missing one from the root
    # package leaves the user with no way to write a VARCHAR(n) or a NUMERIC(p,s) without diving
    # into `snakeorm.fields`.
    snake_str,
    snake_int,
    snake_decimal,
    snake_json,
)


def _public_surface() -> dict[str, object]:
    """The package's public names: attributes without a leading underscore that are NOT submodules.

    The submodules (`snakeorm.fields`, `snakeorm.metadata`...) are attributes because of the import
    itself, not re-exports; they are excluded. What is left is exactly what the facade re-exports.
    """
    return {
        name: value
        for name, value in vars(snakeorm).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }


def _origin_module(value: object) -> str:
    """Module where `value` lives: its own if it is a class/function, its type's if it is an instance."""
    return getattr(value, "__module__", None) or type(value).__module__


def test_essentials_are_exported() -> None:
    """Checks that the minimum surface for declaring, querying and executing is published.

    It is checked by object IDENTITY, not by string: if `snake_column` gets renamed, this test still
    points at the real symbol (or stops importing), not at a literal that went stale.
    """
    public_names = set(_public_surface().values())
    missing = [obj for obj in _ESSENTIALS if obj not in public_names]
    assert missing == []


def test_no_foreign_name_leaks() -> None:
    """Checks that EVERYTHING public is born in `snakeorm`: no stdlib or third-party leaks through.

    Without `__all__`, any non-underscore import in the facade becomes public. This test is the
    guard: a stray `from datetime import datetime as datetime` would export `datetime`, and it would
    trip here because its origin module does not start with `snakeorm`. That is a contract you never
    meant to publish.
    """
    foreign = [
        name
        for name, value in _public_surface().items()
        if not _origin_module(value).startswith("snakeorm")
    ]
    assert foreign == []


def test_a_model_can_be_declared_from_the_root_package() -> None:
    """Checks the real use case: declaring a model importing ONLY from the root package.

    The imports live at the top of the module on purpose: the compiler resolves the annotations
    against the model module's GLOBALS (`compiler.py:_column_hints`), which is the standard
    behaviour of `get_type_hints`. A type imported inside a function would not be visible.
    """

    @snake_model(table="api_probe_users")
    class Probe:
        """Test model declared using the public API only."""

        id: SnakeColumn[int] = snake_auto()
        email: SnakeColumn[str] = snake_str(unique=True)

    table = snake_table(Probe)
    assert table.name == "api_probe_users"
    assert [column.name for column in table.columns] == ["id", "email"]


# The types a public signature may name WITHOUT the root package publishing them, each with the
# reason it is exempt. It is a mapping and not a set for the same purpose the `Cap` catalogue is
# one: the next person has to be able to tell a decision from an oversight, and a bare name in a
# list explains nothing about which of the two it is.
_NOT_PUBLISHED = {
    "SnakeRegistry": (
        "the store of compiled models, reachable as `snakeorm.registry` and deliberately not a "
        "second time through the facade. It surfaces here only through `SnakeQuery.registry`, "
        "which exists so the SESSION can ask a query which registry it resolved against — the same "
        "kind of seam between two internals as `to_many_includes` below, not something an "
        "application calls."
    ),
    "SnakeRelationshipInfo": (
        "a structure of the COMPILED GRAPH, which this module's own docstring keeps out of the "
        "facade on purpose: `snakeorm.metadata` is the one path to it, and publishing a second "
        "would make the generated migrations importable two ways. It surfaces here only through "
        "`SnakeQuery.to_many_includes`, which is how the SESSION asks a query what it carries — a "
        "seam between two internals rather than something an application calls."
    ),
}


def _named_types(annotation: object) -> set[str]:
    """Every `Snake*` identifier an annotation mentions, read as TEXT.

    The annotations are strings here (`from __future__ import annotations` throughout the package),
    and reading them as text is deliberate rather than a shortcut: resolving them would need every
    name to already be importable, which is the very thing being measured.
    """
    return set(re.findall(r"\bSnake[A-Za-z_]*", str(annotation)))


def _public_methods(cls: type) -> dict[str, object]:
    """The public methods and properties DECLARED on a class, with a property read through `fget`."""
    return {
        name: getattr(value, "fget", value)
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(getattr(value, "fget", value))
    }


def test_every_type_a_public_signature_names_can_be_named_by_a_user() -> None:
    """A type in a published signature is importable from the root, or has a published ancestor.

    THE HOLE THIS CLOSES, and it was a real one rather than a hypothesis. `session.all()` accepts
    `SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]` and two of those three could not be named
    from `import snakeorm` at all — so an application that wanted to hand a compound around had no
    way to annotate the variable holding it. In a type-first ORM that is not a missing convenience,
    it is the whole thesis leaking: the checker knows the type and the user cannot write it down.
    The same gap kept `SnakeTypeParams`, `SnakeIndexMethod` and `SnakeFunc` out of reach, which is
    worse where it lands — those three are what a DIALECT's methods take and return, and "a new
    engine is a new file" stops being true when the file cannot be written outside this repository.

    AN ANCESTOR IS ENOUGH, and that is what keeps this test honest rather than merely strict.
    `SnakeValue.is_null()` returns a `SnakeIsNull`, which nobody needs to name: it IS a
    `SnakeCondition`, that is published, and `filter()` takes the supertype. Demanding the leaf be
    exported too would publish a dozen expression nodes to satisfy a rule instead of a user.

    The surface is DERIVED — every public class the facade exports, every public method on it —
    because the facade is a set of re-exports with no `__all__`, and a hand-kept list of what to
    scan is exactly the thing that was already missing five entries when this was written.
    """
    published = {
        value for value in _public_surface().values() if isinstance(value, type)
    }
    unnameable = {
        name: sorted(sites)
        for name, sites in _named_in_public_signatures().items()
        if not _can_be_named(name, published, set()) and name not in _NOT_PUBLISHED
    }

    assert unnameable == {}, (
        f"these types are named in a published signature and cannot be written down by anybody "
        f"importing `snakeorm`: {unnameable}. Either re-export the type, or add it to "
        f"`_NOT_PUBLISHED` above WITH the reason it is not meant to be nameable."
    )


def test_every_exemption_is_still_needed() -> None:
    """Nothing sits in `_NOT_PUBLISHED` after it stopped being unreachable.

    An exemption that no longer applies is worse than none: it reads as a decision that was made
    and is really a note about a signature somebody deleted. This is the same half of the bargain
    the skip catalogues in `conftest.py` strike — a written reason has to expire when it is spent.
    """
    stale = sorted(
        name
        for name in _NOT_PUBLISHED
        if hasattr(snakeorm, name) or name not in _named_in_public_signatures()
    )

    assert stale == [], (
        f"these no longer need an exemption and the reason beside them is now fiction: {stale}"
    )


def _named_in_public_signatures() -> dict[str, set[str]]:
    """Every `Snake*` type a published class names in a published signature, and where."""
    sites: dict[str, set[str]] = {}
    for owner, value in _public_surface().items():
        if not isinstance(value, type):
            continue
        for method, function in _public_methods(value).items():
            for annotation in getattr(function, "__annotations__", {}).values():
                for name in _named_types(annotation):
                    sites.setdefault(name, set()).add(f"{owner}.{method}")
    return sites


def _can_be_named(name: str, published: set[type], seen: set[str]) -> bool:
    """Whether somebody importing only `snakeorm` can write this type down. THREE ways, not one.

    Published outright is the first. Inheriting from something published is the second, and it is
    what keeps a dozen expression nodes out of the facade: `is_null()` returns a `SnakeIsNull` and
    every caller annotates the `SnakeCondition` it is one of.

    The third is an ALIAS whose pieces are all nameable, and it earns its place for a reason with a
    shape: `SnakeCompoundBranch` is a `TypeAlias` written as a STRING and `SnakeCaseBranch` is a
    `tuple[...]`, so neither is an object born in this package at all — publishing them would put a
    bare `str` on the facade and trip `test_no_foreign_name_leaks`, correctly. What the user needs
    is not the alias, it is the ability to spell out what it stands for, and that is exactly what
    this branch measures.
    """
    if name in seen:
        return False
    seen.add(name)
    if hasattr(snakeorm, name):
        return True
    found = _in_subpackages(name)
    if isinstance(found, type):
        return any(base in published for base in found.__mro__[1:])
    if found is None:
        return False
    return all(
        _can_be_named(part, published, seen) for part in _named_types(found) - {name}
    )


def _in_subpackages(name: str) -> object | None:
    """The object behind a name in whichever subpackage re-exports it, or None."""
    for module in _SUBPACKAGES:
        found = getattr(importlib.import_module(module), name, None)
        if found is not None:
            return found
    return None


# Where a type that the root package does not publish can still be found. Every subpackage the
# facade imports from, so the lookup cannot go stale by being narrower than the facade itself.
_SUBPACKAGES = (
    "snakeorm.expressions",
    "snakeorm.query",
    "snakeorm.metadata",
    "snakeorm.fields",
    "snakeorm.dialects",
    "snakeorm.drivers",
    "snakeorm.session",
)
