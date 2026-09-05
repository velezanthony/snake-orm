"""A foreign key whose local column is not on the table is REFUSED, never read as NOT NULL.

`_to_one_is_optional` decides whether crossing a to-one can find nothing, and everything downstream
hangs off its answer: a `True` writes `AuthorDto | None`, a `False` writes `AuthorDto`. It answers
by asking whether any local column of the key is nullable.

It used to skip a pair whose local column it could not find on the table, and `any()` over what is
left of an empty sequence is `False` — so a key it could not read came out NOT NULL. That is the
one direction this function must never fail in: the DTO would promise a value that arrives as
`None`, the checker would believe it, and every reader downstream would too. Nothing anywhere goes
red — which is the ORM storing worse and keeping quiet about it, the one thing it never does.

The pair is `(source_column, target_column)` and the source side belongs to the declaring table, so
this cannot happen while the linker is right. That is exactly why it must raise: an invariant that
holds is worth nothing if breaking it is silent, and a defensive `if` that turns a broken invariant
into a plausible answer is worse than no `if` at all.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto.resolve import _to_one_is_optional
from snakeorm.metadata import (
    SnakeForeignKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
)
from snakeorm.registry import registry_of
from test.dto.domain import FlatPost

_TABLE = registry_of(FlatPost).table_of(FlatPost)


def _relationship(local: str) -> SnakeRelationshipInfo:
    """A to-one whose key reads `local` off the posts table."""
    return SnakeRelationshipInfo(
        name="author",
        target="FlatAuthor",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(target="FlatAuthor", pairs=((local, "id"),)),
    )


def test_a_key_over_a_column_that_is_not_there_is_refused() -> None:
    """THE test: an unreadable key raises instead of coming back as NOT NULL."""
    assert _TABLE is not None

    with pytest.raises(SnakeDtoError, match="no_such_column"):
        _to_one_is_optional(_TABLE, _relationship("no_such_column"))


@pytest.mark.parametrize(
    ("local", "optional"),
    [("editor_id", True), ("author_id", False)],
    ids=["nullable", "not-null"],
)
def test_a_key_it_can_read_is_answered(local: str, optional: bool) -> None:
    """The floor. Without this the test above passes over a function that raises at everything."""
    assert _TABLE is not None

    assert _to_one_is_optional(_TABLE, _relationship(local)) is optional
