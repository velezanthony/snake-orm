"""The classes are written into a MARKED REGION, and nothing outside it is ever touched.

The file has two owners and a visible line between them. Above it, the specs: the user's, hand
written, never edited by this tool. Between the markers, the classes: the generator's, rewritten
whole on every run.

WHY A MARKER IS RIGHT HERE AND WAS WRONG BEFORE. The previous shape of this API filled in a class
body the user had declared, and a sentinel comment inside somebody's own class would have been
litter. Here the generator OWNS whole classes that the user never wrote, so the marker is not
decoration — it is the boundary of ownership, and without it there is no way to tell a generated
class from one somebody typed.

The four properties this file pins down:

    IDEMPOTENCE      two runs leave the file byte for byte identical
    NON-DESTRUCTION  everything outside the markers is the same bytes it went in as
    IT COMPILES      the result is parsed, not just compared as a string
    DRIFT IS SEEN    a model that grows a column shows up as an added field, by name

The last one is the one that justifies the tool. `exclude=` and "neither switch" fail in the OPEN —
a new column is published without anybody deciding to — and this is the only thing that can make
that visible.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto import sync_source

_SPECS = '''"""The DTOs of the feed."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from test.dto.domain import FlatAuthor, FlatPost
    from snakeorm.dto import snake_dto

    # The card the feed renders. Everything in here goes over the wire.
    snake_dto(FlatAuthor, fields=[FlatAuthor.id, FlatAuthor.username], name="AuthorDto")
    snake_dto(FlatPost, fields=[FlatPost.id, FlatPost.title, FlatPost.author], name="PostCard")


def render(card: PostCard) -> str:
    """Hand written, below the region, and it must stay exactly as it is."""
    return card["title"]
'''


def _outside(source: str) -> str:
    """Everything that is NOT the generated region: the two halves of the file joined back up."""
    before, _, rest = source.partition("# snakeorm-dto: begin")
    _, _, after = rest.partition("# snakeorm-dto: end generated block\n")
    return before + after


def test_a_file_with_no_region_gets_one_at_the_end() -> None:
    """The first run appends the region, markers and all, and leaves the rest alone."""
    written = sync_source(_SPECS, path="dto.py").source

    assert written.startswith(_SPECS)
    assert "# snakeorm-dto: begin" in written
    assert "# snakeorm-dto: end" in written
    compile(written, "dto.py", "exec")


def test_the_classes_come_out_in_dependency_order() -> None:
    """`AuthorDto` is written above `PostCard`, because `PostCard` mentions it."""
    written = sync_source(_SPECS, path="dto.py").source

    assert written.index("class AuthorDto") < written.index("class PostCard")


def test_the_nested_field_is_the_other_class() -> None:
    """`Post.author` is written as `author: AuthorDto`, not as the author's columns."""
    written = sync_source(_SPECS, path="dto.py").source

    assert "    author: AuthorDto\n" in written
    assert "username" not in written.split("class PostCard")[1]


def test_running_it_twice_changes_nothing() -> None:
    """The second run is a no-op: identical bytes AND nothing reported as changed.

    Both halves matter. Same bytes with a change reported is a build that stays red over a file that
    is already right; a clean report over different bytes is churn nobody is watching.
    """
    once = sync_source(_SPECS, path="dto.py")
    twice = sync_source(once.source, path="dto.py")

    assert twice.source == once.source
    assert twice.changes == ()
    assert twice.changed is False


def test_everything_outside_the_region_is_untouched() -> None:
    """The specs, their comment, the imports and the function below all survive byte for byte.

    Compared as WHOLE segments rather than by looking for fragments: a fragment check passes over a
    file whose lines were reshuffled, which is exactly the damage worth catching.
    """
    once = sync_source(_SPECS, path="dto.py").source
    damaged = once.replace("    title: str\n", "")

    written = sync_source(damaged, path="dto.py").source

    assert _outside(written) == _outside(once)
    assert _outside(written) == _SPECS + "\n\n"


def test_a_comment_inside_the_type_checking_block_survives() -> None:
    """The specs are the user's file, and a comment among them is theirs too."""
    written = sync_source(_SPECS, path="dto.py").source

    assert "# The card the feed renders. Everything in here goes over the wire." in (
        written
    )


def test_a_model_that_gained_a_column_is_reported_by_name() -> None:
    """THE reason the tool earns its keep, on the switch that fails in the open.

    With `exclude=`, a column added to the model is published the day it is added and nobody chose
    that. Here the region goes out of date and the check names the field that appeared.
    """
    source = _SPECS.replace(
        '    snake_dto(FlatPost, fields=[FlatPost.id, FlatPost.title, FlatPost.author], name="PostCard")',
        '    snake_dto(FlatPost, exclude=[FlatPost.author_id], name="PostCard")',
    )
    stale = sync_source(source, path="dto.py").source
    shrunk = stale.replace("    editor_id: int | None\n", "")

    result = sync_source(shrunk, path="dto.py")

    assert result.changed is True
    assert [change.describe() for change in result.changes] == [
        "PostCard: added `editor_id: int | None`"
    ]


def test_a_field_that_left_the_model_is_reported_too() -> None:
    """The other direction: something in the region that the specs no longer produce."""
    stale = sync_source(_SPECS, path="dto.py").source.replace(
        "    author: AuthorDto\n", "    author: AuthorDto\n    ghost: str\n"
    )

    result = sync_source(stale, path="dto.py")

    assert [change.describe() for change in result.changes] == [
        "PostCard: removed `ghost: str`"
    ]


def test_a_field_whose_type_changed_is_reported_as_retyped() -> None:
    """An annotation that drifted is corrected, with both sides quoted."""
    stale = sync_source(_SPECS, path="dto.py").source.replace(
        "    title: str\n", "    title: int\n"
    )

    result = sync_source(stale, path="dto.py")

    assert [change.describe() for change in result.changes] == [
        "PostCard: retyped `title: int` -> `title: str`"
    ]


def test_a_region_with_no_end_marker_is_refused() -> None:
    """An unterminated region has no end to write up to, and guessing one would eat the file."""
    broken = _SPECS + "# snakeorm-dto: begin generated block\n\n\nx = 1\n"

    with pytest.raises(SnakeDtoError) as failure:
        sync_source(broken, path="dto.py")

    message = str(failure.value)
    assert "dto.py" in message
    assert "end" in message


def test_two_regions_are_refused() -> None:
    """Two regions and no rule about which is the real one, so neither is written."""
    once = sync_source(_SPECS, path="dto.py").source
    _, marker, region = once.partition("# snakeorm-dto: begin")

    with pytest.raises(SnakeDtoError) as failure:
        sync_source(once + marker + region, path="dto.py")

    assert "more than one" in str(failure.value)


def test_a_missing_typed_dict_import_is_refused() -> None:
    """The generator writes `class X(TypedDict)`, and never writes the import that makes it work.

    Writing the import would be editing the user's import block on a guess; writing the class
    without it produces a file that does not type-check. Saying which line to add cannot go wrong.
    """
    source = _SPECS.replace(
        "from typing import TYPE_CHECKING, TypedDict",
        "from typing import TYPE_CHECKING",
    )

    with pytest.raises(SnakeDtoError) as failure:
        sync_source(source, path="dto.py")

    message = str(failure.value)
    assert "TypedDict" in message
    assert "from typing import TypedDict" in message


def test_a_missing_annotation_import_is_refused() -> None:
    """Same rule for a field's own type: `datetime.datetime` needs `datetime` in scope."""
    source = """from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from test.dto.domain import DtoUser
    from snakeorm.dto import snake_dto

    snake_dto(DtoUser, fields=[DtoUser.created_at], name="Stamp")
"""

    with pytest.raises(SnakeDtoError) as failure:
        sync_source(source, path="dto.py")

    message = str(failure.value)
    assert "datetime.datetime" in message
    assert "import datetime" in message


def test_the_import_being_there_lets_it_through() -> None:
    """The same file with the import writes the field, qualified and resolvable."""
    source = """from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from test.dto.domain import DtoUser
    from snakeorm.dto import snake_dto

    snake_dto(DtoUser, fields=[DtoUser.created_at], name="Stamp")
"""

    written = sync_source(source, path="dto.py").source

    assert "    created_at: datetime.datetime\n" in written
    compile(written, "dto.py", "exec")


def test_a_file_with_no_specs_is_left_alone() -> None:
    """No declarations means no region and no changes, not an empty region appended."""
    source = '"""Nothing to declare."""\n'

    result = sync_source(source, path="dto.py")

    assert result.source == source
    assert result.changed is False
