"""`SnakeRelationshipNotLoaded` is an `AttributeError`, so `hasattr` and `getattr` eat it silently.

This asserts the CURRENT behaviour, and it is not an endorsement of it. It is here because the hole
is invisible from every direction a reader normally looks:

    post.author                     ->  SnakeRelationshipNotLoaded    loud
    hasattr(post, "author")         ->  False                         silent
    getattr(post, "author", None)   ->  None                          silent

`hasattr` is defined as "call getattr and see whether it raises AttributeError", and the
three-argument `getattr` swallows exactly that class. So the ORM's loudest guarantee — that a
relation nobody loaded cannot be read by accident — evaporates the moment the caller uses the
reflective form.

WHY THIS MATTERS TO THE GENERATED DTOs, which is why the test lives here. A serializer walking a
shape is written with `getattr(row, name, ...)` — that IS how they are written, because the names
come from data. Feed it a row that was queried without `include(...)` and a relation the DTO types
as `author: AuthorDto` arrives as `None`, or vanishes from the payload entirely. The type checker
agrees the whole way to the front end, because the type is right; only the value is wrong.

WHY IT IS NOT FIXED. The `AttributeError` base is deliberate and pinned by
`src/test/exceptions/test_exceptions.py`: it is what lets ordinary Python code —`copy`, `pickle`,
`dataclasses`, anything that probes an object— treat a model like an object instead of exploding.
Changing the base to trade one silent failure for a much broader loud one is not obviously the
better deal, and it is not this file's call to make.

So it is written down and watched. If the base ever changes, this file goes red and whoever changed
it reads the reason it was this way — which is the whole point of pinning a behaviour you dislike
rather than leaving it undocumented.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeRelationshipNotLoaded
from test.dto.domain import FlatPost


@pytest.fixture
def unloaded() -> FlatPost:
    """A row built by hand: no query ran, so nothing is loaded. That is the state under test."""
    return FlatPost(title="x", author_id=1, editor_id=None)


def test_reading_it_directly_is_loud(unloaded: FlatPost) -> None:
    """The floor. Without this, the rest of the file would be pinning a hole that is everywhere."""
    with pytest.raises(
        SnakeRelationshipNotLoaded, match=r"include\(FlatPost\.author\)"
    ):
        unloaded.author


def test_hasattr_answers_False_instead_of_raising(unloaded: FlatPost) -> None:
    """`hasattr` reports the relation as ABSENT, which is not what "not loaded" means.

    A caller branching on `hasattr` skips the field and ships a payload missing a key the DTO
    declares — and `TypedDict` totality means the checker believed that key was there.
    """
    assert hasattr(unloaded, "author") is False


def test_getattr_with_a_default_returns_the_default(unloaded: FlatPost) -> None:
    """The dangerous one: the relation comes back as whatever the serializer passed as a fallback.

    `None` is the fallback everybody writes, and `None` is also a legitimate value for a nullable
    to-one. So this failure is indistinguishable, at the call site, from the truth.
    """
    assert getattr(unloaded, "author", None) is None
    assert getattr(unloaded, "author", "fallback") == "fallback"


def test_the_two_argument_form_still_shouts(unloaded: FlatPost) -> None:
    """The way out, and the reason this is a trap rather than a defect: `getattr` without a default.

    Every `getattr` in `src/snakeorm/session/` is the two-argument form, which is why the ORM does
    not trip over its own hole. A serializer that does the same keeps the guarantee.
    """
    with pytest.raises(
        SnakeRelationshipNotLoaded, match=r"include\(FlatPost\.author\)"
    ):
        getattr(unloaded, "author")  # noqa: B009 - the two-argument form is the point


def test_it_really_is_an_AttributeError(unloaded: FlatPost) -> None:
    """The premise. Everything above follows from this one fact, so it is asserted and not assumed.

    If the base ever changes, the three tests above start failing for a reason that has nothing to
    do with what they are named after. This one names it.
    """
    assert issubclass(SnakeRelationshipNotLoaded, AttributeError)
