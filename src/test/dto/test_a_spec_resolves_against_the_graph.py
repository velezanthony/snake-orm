"""Turning declared specs into the shapes that get written: types, nesting, and the order to write them in.

Three things happen here and each has a way of being quietly wrong.

NULLABILITY comes from walking the WHOLE path, never from the column at the end. `editor.username`
is `str | None` although `username` is NOT NULL, because a LEFT JOIN over a nullable `editor_id`
genuinely returns nothing. The same rule decides a NESTED field: `Post.editor` is
`AuthorDto | None` for exactly the reason `editor.username` is `str | None`.

NESTING resolves to another SPEC, never to the far model's columns. `Post.author` becomes
`author: AuthorDto`, and which `AuthorDto` is decided by looking for a spec over that model. None
found is an error; more than one found is an error naming the candidates. Picking "whichever" would
be bug #14 in another costume: it does not fail, it publishes the wrong shape.

ORDER is by DEPENDENCY, not by declaration. `AuthorDto` has to be written before `PostCard` or the
file does not compile, whichever order the user wrote the two lines in. A cycle has no such order,
so it is named and refused rather than guessed at.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto import SnakeDtoSpec, resolve_all, snake_dto, specs_in_source
from test.dto.domain import FlatAuthor, FlatComment, FlatCountry, FlatPost


def _shapes(*specs: SnakeDtoSpec) -> dict[str, dict[str, str]]:
    """`{class name: {field: annotation}}` for the given specs, resolved together."""
    return {
        shape.name: {field.name: field.annotation for field in shape.fields}
        for shape in resolve_all(specs)
    }


def _from_source(switch: str) -> dict[str, dict[str, str]]:
    """The same resolution, driven through the AST reader instead of through descriptors.

    THIS HELPER USED TO BE A DETOUR, AND IS NOT ONE ANY MORE. It existed because the tests whose
    path crosses a NULLABLE to-one could not be written with descriptors at all: class access on
    `SnakeToOne[M | None]` was `type[M] | type[None]`, so `FlatPost.editor.username` did not
    type-check in this file. Its docstring said these tests could "come back" the day that was
    fixed, and it has been — `SnakeToOne.__get__` now unwraps the `| None` through an overload on
    the type of `self`, and the tests below write the descriptor path directly.

    What kept the helper alive is the half of its old justification that was never about the
    limitation: this IS the route `snake_dto` takes from the command line, reading specs out of
    source text it never imports. So it stays as the cross-check in
    `test_both_routes_agree_on_a_path_across_a_nullable_hop`, which pins the two readers to one
    answer — a real risk now that the descriptor route is the one everything else uses, and the
    reader could drift under it unnoticed.
    """
    source = (
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from test.dto.domain import FlatPost\n"
        "    from snakeorm.dto import snake_dto\n\n"
        f'    snake_dto(FlatPost, {switch}, name="Card")\n'
    )
    return {
        shape.name: {field.name: field.annotation for field in shape.fields}
        for shape in resolve_all(specs_in_source(source, path="dto.py"))
    }


def test_a_plain_column_takes_its_python_type() -> None:
    """`Post.title` over a NOT NULL text column is a `str`."""
    spec = snake_dto(FlatPost, fields=[FlatPost.id, FlatPost.title], name="Card")

    assert _shapes(spec)["Card"] == {"id": "int", "title": "str"}


def test_a_nullable_column_carries_its_none() -> None:
    """`Post.editor_id` is nullable in the model, so it is `int | None` in the DTO."""
    spec = snake_dto(FlatPost, fields=[FlatPost.editor_id], name="Card")

    assert _shapes(spec)["Card"]["editor_id"] == "int | None"


def test_a_deep_column_is_named_after_its_whole_path() -> None:
    """`Post.author.username` becomes `author_username`, which is what a flat DTO is written like.

    Named mechanically off the path so two paths can never land on one key: `author.username` and
    `editor.username` would both be `username` if only the last step counted, and one would
    overwrite the other in silence.

    Written with descriptors, `FlatPost.editor.username` included. That line used to be unwritable
    here and this test went through the AST reader to get at it; the descriptor now unwraps the
    `| None` on class access, so the test says what it means.
    """
    spec = snake_dto(
        FlatPost,
        fields=[FlatPost.author.username, FlatPost.editor.username],
        name="Card",
    )

    assert set(_shapes(spec)["Card"]) == {"author_username", "editor_username"}


def test_a_nullable_hop_makes_a_deep_column_optional() -> None:
    """The controlled experiment: same target, same final column, one nullable key between them.

    It is also the end-to-end proof of the descriptor fix. The typing tests show the CHECKER accepts
    `FlatPost.editor.username`; this shows the ORM actually resolves that path at runtime and gets
    its nullability right — the two halves the fix had to satisfy at once.
    """
    spec = snake_dto(
        FlatPost,
        fields=[FlatPost.author.username, FlatPost.editor.username],
        name="Card",
    )
    shape = _shapes(spec)["Card"]

    assert shape["author_username"] == "str"
    assert shape["editor_username"] == "str | None"


def test_the_nullable_hop_counts_from_anywhere_along_the_path() -> None:
    """`author.country.name`: required hop, nullable hop, NOT NULL column.

    Reading the last step gives `str`. Reading the first hop gives `str`. Only accumulating over
    every hop gives the truth.
    """
    spec = snake_dto(FlatPost, fields=[FlatPost.author.country.name], name="Card")

    assert _shapes(spec)["Card"]["author_country_name"] == "str | None"


def test_both_routes_agree_on_a_path_across_a_nullable_hop() -> None:
    """The descriptor route and the AST reader resolve the same path to the same shape.

    `snake_dto` is reached two ways: from a live model, where the path comes out of the descriptors,
    and from the command line, where `specs_in_source` reads it out of text it never imports. They
    have to agree, and until now nothing said so — the nullable-path tests could only be written one
    way, so the two readers were never compared on the case where getting nullability wrong is
    easiest.

    Now that the descriptor route can express it, this is what keeps the reader from drifting under
    the route everything else uses.
    """
    from_descriptors = _shapes(
        snake_dto(
            FlatPost,
            fields=[FlatPost.author.username, FlatPost.editor.username],
            name="Card",
        )
    )

    assert (
        _from_source("fields=[FlatPost.author.username, FlatPost.editor.username]")
        == from_descriptors
    )


def test_a_to_one_nests_the_spec_of_its_model() -> None:
    """`Post.author` is `author: AuthorDto`, and not the author's columns spread out here."""
    author = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")
    post = snake_dto(FlatPost, fields=[FlatPost.id, FlatPost.author], name="PostCard")

    assert _shapes(author, post)["PostCard"] == {"id": "int", "author": "AuthorDto"}


def test_a_nested_field_across_a_nullable_key_is_optional() -> None:
    """`Post.editor` is `AuthorDto | None`, for the reason `editor.username` is `str | None`."""
    author = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")
    post = snake_dto(FlatPost, fields=[FlatPost.editor], name="PostCard")

    assert _shapes(author, post)["PostCard"]["editor"] == "AuthorDto | None"


def test_a_to_many_nests_as_a_list() -> None:
    """`Post.comments` is `list[CommentDto]`.

    A list IS one value, which is why this is allowed where a flattened `comments.body` was not: a
    collection has no single value to flatten, and it has a perfectly good plural type. No `| None`
    either — a parent with no children gets `[]`, which is what the select-in returns.
    """
    comment = snake_dto(FlatComment, fields=[FlatComment.id], name="CommentDto")
    post = snake_dto(FlatPost, fields=[FlatPost.comments], name="PostCard")

    assert _shapes(comment, post)["PostCard"]["comments"] == "list[CommentDto]"


def test_a_model_with_no_spec_is_named() -> None:
    """Nesting needs a spec for the far model, and says which model is missing one."""
    post = snake_dto(FlatPost, fields=[FlatPost.author], name="PostCard")

    with pytest.raises(SnakeDtoError) as failure:
        _shapes(post)

    message = str(failure.value)
    assert "FlatAuthor" in message
    assert "author" in message


def test_two_specs_for_one_model_are_refused_by_name() -> None:
    """Two candidates and no rule to pick between them, so both are named and neither is used.

    Choosing "whichever" is how the wrong shape gets published without anybody noticing — the same
    defect as resolving a model by class name when two applications declare one.
    """
    first = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")
    second = snake_dto(FlatAuthor, fields=[FlatAuthor.username], name="AuthorCard")
    post = snake_dto(FlatPost, fields=[FlatPost.author], name="PostCard")

    with pytest.raises(SnakeDtoError) as failure:
        _shapes(first, second, post)

    message = str(failure.value)
    assert "AuthorCard" in message
    assert "AuthorDto" in message
    assert "(FlatPost.author, " in message


def test_the_pair_form_picks_one_of_the_candidates() -> None:
    """`(Post.author, "AuthorCard")` says which, and the ambiguity is gone."""
    first = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")
    second = snake_dto(FlatAuthor, fields=[FlatAuthor.username], name="AuthorCard")
    post = snake_dto(
        FlatPost, fields=[(FlatPost.author, "AuthorCard")], name="PostCard"
    )

    assert _shapes(first, second, post)["PostCard"]["author"] == "AuthorCard"


def test_a_named_dto_that_does_not_exist_is_refused() -> None:
    """A pair naming a spec nobody declared names it, and lists the ones over that model."""
    author = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")
    post = snake_dto(FlatPost, fields=[(FlatPost.author, "Nope")], name="PostCard")

    with pytest.raises(SnakeDtoError) as failure:
        _shapes(author, post)

    message = str(failure.value)
    assert "'Nope'" in message
    assert "AuthorDto" in message


def test_a_named_dto_over_the_wrong_model_is_refused() -> None:
    """Naming a spec that describes another model entirely is caught, not written.

    It type-checks (a string is a string) and it produces a class whose fields belong to a different
    table, which is the failure this whole nesting rule exists to prevent.
    """
    wrong = snake_dto(FlatCountry, fields=[FlatCountry.id], name="CountryDto")
    post = snake_dto(
        FlatPost, fields=[(FlatPost.author, "CountryDto")], name="PostCard"
    )

    with pytest.raises(SnakeDtoError) as failure:
        _shapes(wrong, post)

    message = str(failure.value)
    assert "CountryDto" in message
    assert "FlatCountry" in message
    assert "FlatAuthor" in message


def test_the_dependency_decides_the_order_not_the_declaration() -> None:
    """`PostCard` is declared FIRST and written SECOND, because it nests `AuthorDto`.

    Python reads a file top to bottom: a class that mentions another has to come after it. Writing
    in declaration order produces a file that does not import, and it would do so only for the users
    who happened to write their two lines the other way round.
    """
    post = snake_dto(FlatPost, fields=[FlatPost.author], name="PostCard")
    author = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")

    resolved = resolve_all([post, author])

    assert [shape.name for shape in resolved] == ["AuthorDto", "PostCard"]


def test_specs_that_depend_on_nothing_keep_their_declaration_order() -> None:
    """With no dependency to satisfy, the file reads in the order it was written.

    A sort that reshuffled independent classes would churn the region for no reason, and the diff
    is the whole product here.
    """
    first = snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="Bbb")
    second = snake_dto(FlatCountry, fields=[FlatCountry.id], name="Aaa")

    resolved = resolve_all([first, second])

    assert [shape.name for shape in resolved] == ["Bbb", "Aaa"]


def test_a_cycle_between_two_specs_is_named_and_refused() -> None:
    """A nests B and B nests A: there is no order, so both are named instead of one being guessed."""
    post = snake_dto(FlatPost, fields=[FlatPost.comments], name="PostCard")
    comment = snake_dto(FlatComment, fields=[FlatComment.post], name="CommentDto")

    with pytest.raises(SnakeDtoError) as failure:
        _shapes(post, comment)

    message = str(failure.value)
    assert "PostCard" in message
    assert "CommentDto" in message
    assert "cycle" in message


def test_no_switch_means_every_column_and_no_relationship() -> None:
    """Neither switch is every COLUMN. A relationship is never pulled in by default.

    Defaulting to nesting would make an innocent-looking declaration drag a whole object graph into
    a response, and it could not be written at all without a spec for every model it reached.
    """
    spec = snake_dto(FlatPost, name="PostCard")

    assert list(_shapes(spec)["PostCard"]) == [
        "id",
        "title",
        "author_id",
        "editor_id",
    ]


def test_exclude_is_every_column_but_those() -> None:
    """`exclude` prunes the same list neither-switch produces."""
    spec = snake_dto(
        FlatPost, exclude=[FlatPost.author_id, FlatPost.editor_id], name="PostCard"
    )

    assert list(_shapes(spec)["PostCard"]) == ["id", "title"]


def test_a_path_the_model_does_not_have_is_refused() -> None:
    """A path built against one model and used on another is caught by the graph, not by luck.

    It cannot happen through the descriptors — that is what the checker is for — but a spec can be
    built by hand, and the resolution is where the graph gets the last word.
    """
    from snakeorm.dto import SnakeDtoPick

    spec = SnakeDtoSpec(
        model=FlatPost,
        name="PostCard",
        fields=(SnakeDtoPick(path=("nope",)),),
    )

    with pytest.raises(SnakeDtoError) as failure:
        resolve_all([spec])

    assert "'nope'" in str(failure.value)
