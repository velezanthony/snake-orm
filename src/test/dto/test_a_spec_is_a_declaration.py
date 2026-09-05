"""`snake_dto(...)` is a DECLARATION, not a decorator: the user writes the spec, the CLI writes the class.

The shape of a response is stated once, as data, in the file that owns it:

    snake_dto(Post, fields=[Post.id, Post.title, Post.author], name="PostCard")

WHY DESCRIPTORS AND NOT STRINGS. `Post.tilte` does not compile — measured, both mypy and pyright
reject it — whereas `fields=["tilte"]` is a perfectly good string that only blows up when somebody
runs the generator. It is the difference between a typo the editor underlines and a typo that ships.

WHY `name=` IS MANDATORY. The class does not exist yet, so nothing else can supply it. The old shape
of this API had the user declare an empty class for the generator to fill; this one has no class to
read a name off, and defaulting it to something derived from the model would be a rule with a
special case for every collision.

WHAT AN ENTRY MAY BE, and the three are told apart by their RUNTIME type, which is exact:

    Post.title            SnakeExpr        a column
    Post.author.username  SnakeExpr        a column across a to-one, path ('author', 'username')
    Post.author           SnakePathProxy   a to-one relationship, nested
    Post.comments         SnakeCollection  a to-many, nested as a list
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto import snake_dto
from test.dto.domain import FlatPost


def test_a_spec_records_the_paths_it_was_given() -> None:
    """Each entry is normalised to the PATH it names, in the order it was written."""
    spec = snake_dto(
        FlatPost,
        fields=[FlatPost.id, FlatPost.title, FlatPost.author.username],
        name="Card1",
    )

    assert spec.name == "Card1"
    assert spec.model is FlatPost
    assert [pick.path for pick in spec.fields or ()] == [
        ("id",),
        ("title",),
        ("author", "username"),
    ]


def test_a_relationship_entry_is_recorded_as_its_path_too() -> None:
    """A to-one and a to-many normalise the same way. What they MEAN is decided by the graph.

    Storing the runtime kind here would be a second source for a fact the metadata already holds,
    and the two would eventually disagree about what `('author',)` is.
    """
    spec = snake_dto(
        FlatPost, fields=[FlatPost.author, FlatPost.comments], name="Card2"
    )

    assert [pick.path for pick in spec.fields or ()] == [("author",), ("comments",)]


def test_an_entry_can_name_the_nested_dto_explicitly() -> None:
    """`(Post.author, "AuthorCard")` says WHICH spec to nest, for when a model has several."""
    spec = snake_dto(
        FlatPost, fields=[FlatPost.id, (FlatPost.author, "AuthorCard")], name="Card3"
    )

    picks = spec.fields or ()
    assert picks[1].path == ("author",)
    assert picks[1].dto == "AuthorCard"


def test_exclude_records_its_paths() -> None:
    """`exclude` is the other switch, and it takes descriptors just the same."""
    spec = snake_dto(FlatPost, exclude=[FlatPost.editor_id], name="Card4")

    assert spec.fields is None
    assert spec.exclude == (("editor_id",),)


def test_fields_and_exclude_together_are_refused() -> None:
    """Two ways of answering the same question, and they can disagree."""
    with pytest.raises(SnakeDtoError) as failure:
        snake_dto(
            FlatPost, fields=[FlatPost.id], exclude=[FlatPost.title], name="Card5"
        )

    assert "both fields= and exclude=" in str(failure.value)


def test_an_excluded_path_has_to_be_a_column_of_this_model() -> None:
    """`exclude` prunes THIS model's columns; a path across a relationship prunes nothing.

    `exclude=[Post.author.username]` reads as if it removed something, and there is nothing there to
    remove: the author's columns are not in this DTO in the first place.
    """
    with pytest.raises(SnakeDtoError) as failure:
        snake_dto(FlatPost, exclude=[FlatPost.author.username], name="Card6")

    message = str(failure.value)
    assert "author.username" in message
    assert "one column of" in message


def test_something_that_is_not_a_field_is_refused_by_name() -> None:
    """A value that names no path says what it was, instead of being skipped or crashing later."""
    with pytest.raises(SnakeDtoError) as failure:
        snake_dto(FlatPost, fields=[FlatPost.id, 42], name="Card7")  # type: ignore[list-item]

    message = str(failure.value)
    assert "int" in message
    assert "Card7" in message


def test_a_name_that_is_not_an_identifier_is_refused() -> None:
    """The name becomes `class <name>(TypedDict)`, so it has to be writable as one."""
    with pytest.raises(SnakeDtoError) as failure:
        snake_dto(FlatPost, fields=[FlatPost.id], name="Post Card")

    assert "not a valid class name" in str(failure.value)


def test_a_name_that_is_a_keyword_is_refused() -> None:
    """`class import(TypedDict)` is a syntax error, and it is knowable here."""
    with pytest.raises(SnakeDtoError) as failure:
        snake_dto(FlatPost, fields=[FlatPost.id], name="import")

    assert "not a valid class name" in str(failure.value)


def test_a_model_that_was_never_compiled_is_refused() -> None:
    """Nothing to read columns from, said at the line that named it."""

    class NotAModel:
        """Never went through @snake_model."""

    with pytest.raises(SnakeDtoError) as failure:
        snake_dto(NotAModel, name="Card8")

    assert "is not a compiled model" in str(failure.value)


def test_a_spec_is_returned_and_nothing_is_registered() -> None:
    """The call RETURNS the spec and keeps no global state, because it is never reached at runtime.

    In the file it is written in, this line lives under `if TYPE_CHECKING:` and the interpreter walks
    straight past it. A process-wide list of declarations would be a list that is always empty in
    production and full in tests — a mechanism whose two halves never see the same thing.
    """
    spec = snake_dto(FlatPost, fields=[FlatPost.id], name="Card9")

    assert spec.name == "Card9"
    assert snake_dto(FlatPost, fields=[FlatPost.id], name="Card9") == spec
