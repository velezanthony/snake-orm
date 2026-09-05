"""The generator READS the declarations out of the file. It never imports the file, never runs it.

The specs live inside `if TYPE_CHECKING:`, which means the interpreter walks past them and only a
type checker ever looks. Three properties come out of that arrangement, and all three are measured
in this package rather than assumed:

    mypy and pyright over `Post.tilte` in the block  ->  error: "type[Post]" has no attribute
    importing the DTO module at runtime              ->  clean, nothing in the block runs
    importing the DTO module at runtime              ->  does not drag in `blog.models` either

So the file costs nothing to import, the import cycle between `models.py` and `dto.py` cannot form,
and every path is still validated by the checker at the line it was written on.

What that buys HERE is the property this file is named after: a tool that rewrites your file does
not execute your file. The only thing imported is the MODELS module, because the compiled metadata
is where the types, the nullability and the relationships live. The AST gives the names; the
`SnakeTableInfo` gives the truth.

And reading beats evaluating in one more way that is not just safety. The source says which name a
path is ROOTED at — `Post.author.username` starts at `Post` — and the evaluated descriptor does not:
`SnakeExpr` carries `('author', 'username')` and has forgotten whose. So a spec over `Post` that
selects `Author.id` is catchable here and was invisible before.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto import specs_in_source

_HEAD = '''"""The DTOs of the feed."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from test.dto.domain import FlatAuthor, FlatPost
    from snakeorm.dto import snake_dto

'''


def _specs(body: str) -> tuple[object, ...]:
    """The specs read out of a file whose `TYPE_CHECKING` block holds `body`."""
    return specs_in_source(_HEAD + body, path="dto.py")


def test_a_declaration_is_read_out_of_the_type_checking_block() -> None:
    """The ordinary case: one call, one spec, with its model resolved to the real class."""
    from test.dto.domain import FlatPost

    specs = _specs(
        '    snake_dto(FlatPost, fields=[FlatPost.id, FlatPost.title], name="PostCard")\n'
    )

    assert len(specs) == 1
    spec = specs[0]
    assert spec.name == "PostCard"  # type: ignore[attr-defined]
    assert spec.model is FlatPost  # type: ignore[attr-defined]
    assert [pick.path for pick in spec.fields] == [("id",), ("title",)]  # type: ignore[attr-defined]


def test_a_deep_path_is_read_as_its_whole_chain() -> None:
    """`FlatPost.author.username` is read as `('author', 'username')`, straight off the attributes."""
    specs = _specs(
        '    snake_dto(FlatPost, fields=[FlatPost.author.username], name="PostCard")\n'
    )

    assert [pick.path for pick in specs[0].fields] == [("author", "username")]  # type: ignore[attr-defined]


def test_a_relationship_is_read_as_a_one_step_path() -> None:
    """`FlatPost.author` on its own is a path of one step; the graph decides it is a relationship."""
    specs = _specs(
        '    snake_dto(FlatPost, fields=[FlatPost.author], name="PostCard")\n'
    )

    assert [pick.path for pick in specs[0].fields] == [("author",)]  # type: ignore[attr-defined]


def test_the_pair_form_is_read_with_its_dto_name() -> None:
    """`(FlatPost.author, "AuthorCard")` keeps the name it was disambiguated with."""
    specs = _specs(
        '    snake_dto(FlatPost, fields=[(FlatPost.author, "AuthorCard")], name="PostCard")\n'
    )

    pick = specs[0].fields[0]  # type: ignore[attr-defined]
    assert pick.path == ("author",)
    assert pick.dto == "AuthorCard"


def test_exclude_is_read_the_same_way() -> None:
    """The other switch reads identically, and `fields` comes back as `None`."""
    specs = _specs(
        '    snake_dto(FlatPost, exclude=[FlatPost.editor_id], name="PostCard")\n'
    )

    assert specs[0].fields is None  # type: ignore[attr-defined]
    assert specs[0].exclude == (("editor_id",),)  # type: ignore[attr-defined]


def test_neither_switch_reads_as_neither() -> None:
    """A bare declaration is every column, and it survives the trip through the AST as `None`."""
    specs = _specs('    snake_dto(FlatPost, name="PostCard")\n')

    assert specs[0].fields is None  # type: ignore[attr-defined]
    assert specs[0].exclude == ()  # type: ignore[attr-defined]


def test_two_declarations_come_back_in_the_order_they_were_written() -> None:
    """Declaration order is what the reader answers. The WRITE order is `resolve_all`'s question."""
    specs = _specs(
        '    snake_dto(FlatPost, fields=[FlatPost.id], name="PostCard")\n'
        '    snake_dto(FlatAuthor, fields=[FlatAuthor.id], name="AuthorDto")\n'
    )

    assert [spec.name for spec in specs] == ["PostCard", "AuthorDto"]  # type: ignore[attr-defined]


def test_the_guard_can_be_written_as_an_attribute() -> None:
    """`if typing.TYPE_CHECKING:` counts as much as `if TYPE_CHECKING:`.

    Recognising only the bare name would reject a file that is perfectly correct — the same
    fail-in-the-open shape as checking a TypedDict by the name of its base class.
    """
    source = """from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from test.dto.domain import FlatPost
    from snakeorm.dto import snake_dto

    snake_dto(FlatPost, fields=[FlatPost.id], name="PostCard")
"""

    assert [spec.name for spec in specs_in_source(source, path="dto.py")] == [  # type: ignore[attr-defined]
        "PostCard"
    ]


def test_a_declaration_at_module_level_is_read_too() -> None:
    """Outside the block it still reads. Where it goes is the user's call, not the generator's.

    Under `TYPE_CHECKING` costs nothing to import and cannot form a cycle, which is why it is what
    the documentation shows. At module level it runs for real and needs real imports — a legitimate
    choice with a different price, and refusing it would be this tool having an opinion about
    somebody's import graph.
    """
    source = """from __future__ import annotations

from test.dto.domain import FlatPost
from snakeorm.dto import snake_dto

snake_dto(FlatPost, fields=[FlatPost.id], name="PostCard")
"""

    assert len(specs_in_source(source, path="dto.py")) == 1


def test_the_function_can_be_imported_under_another_name() -> None:
    """`from snakeorm.dto import snake_dto as dto` still reads, because the IMPORT is what is matched.

    Matching the literal text `snake_dto` would be a list of one accepted spelling, and an alias is
    a perfectly ordinary thing to write.
    """
    source = """from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from test.dto.domain import FlatPost
    from snakeorm.dto import snake_dto as dto

    dto(FlatPost, fields=[FlatPost.id], name="PostCard")
"""

    assert len(specs_in_source(source, path="dto.py")) == 1


def test_a_call_to_something_else_is_not_read() -> None:
    """A local function that happens to be called `snake_dto` is not this one, and is left alone."""
    source = '''from __future__ import annotations


def snake_dto(model: object, **kwargs: object) -> None:
    """Somebody else's function of the same name."""


snake_dto(object, name="NotOurs")
'''

    assert specs_in_source(source, path="dto.py") == ()


def test_a_model_the_file_does_not_import_is_refused() -> None:
    """The model name is resolved through the file's own imports, and says so when there is none."""
    source = """from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from snakeorm.dto import snake_dto

    snake_dto(FlatPost, fields=[FlatPost.id], name="PostCard")
"""

    with pytest.raises(SnakeDtoError) as failure:
        specs_in_source(source, path="dto.py")

    message = str(failure.value)
    assert "'FlatPost'" in message
    assert "dto.py" in message


def test_a_field_rooted_at_another_model_is_refused() -> None:
    """`snake_dto(FlatPost, fields=[FlatAuthor.id])` is caught, and it could not be before.

    This is what reading buys over evaluating. The descriptor `FlatAuthor.id` evaluates to a
    `SnakeExpr` carrying `('id',)` and NOTHING about whose `id` it is — and `FlatPost` has an `id`
    too, so the old shape of this API resolved it happily against the wrong model. The source still
    says `FlatAuthor`, so here it is a refusal.
    """
    with pytest.raises(SnakeDtoError) as failure:
        _specs('    snake_dto(FlatPost, fields=[FlatAuthor.id], name="PostCard")\n')

    message = str(failure.value)
    assert "FlatAuthor.id" in message
    assert "FlatPost" in message


def test_a_missing_name_is_refused() -> None:
    """`name=` is what the class is called, so a declaration without one describes nothing."""
    with pytest.raises(SnakeDtoError) as failure:
        _specs("    snake_dto(FlatPost, fields=[FlatPost.id])\n")

    assert "name=" in str(failure.value)


def test_a_name_that_is_not_a_literal_is_refused() -> None:
    """The name has to be readable without running anything, which is the point of reading."""
    with pytest.raises(SnakeDtoError) as failure:
        _specs('    snake_dto(FlatPost, fields=[FlatPost.id], name="Post" + "Card")\n')

    assert "a plain string" in str(failure.value)


def test_a_field_that_is_not_an_attribute_chain_is_refused() -> None:
    """`fields=["id"]` names nothing the checker validated, and is refused rather than parsed."""
    with pytest.raises(SnakeDtoError) as failure:
        _specs('    snake_dto(FlatPost, fields=["id"], name="PostCard")\n')

    message = str(failure.value)
    assert "PostCard" in message
    assert "class access" in message


def test_the_error_names_the_line_it_is_on() -> None:
    """A file holds several declarations, so a complaint that does not say WHICH is a search."""
    with pytest.raises(SnakeDtoError) as failure:
        _specs(
            '    snake_dto(FlatPost, fields=[FlatPost.id], name="Good")\n'
            '    snake_dto(FlatPost, fields=["id"], name="Bad")\n'
        )

    assert "dto.py:12" in str(failure.value)


_SHOP = """from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from test.dto.homonyms.shop.models import Customer
    from snakeorm.dto import snake_dto

    snake_dto(Customer, fields=[Customer.id, Customer.sku], name="ShopCard")
"""

_CRM = """from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from test.dto.homonyms.crm.models import Customer
    from snakeorm.dto import snake_dto

    snake_dto(Customer, fields=[Customer.id, Customer.account], name="CrmCard")
"""


def test_two_applications_with_a_customer_each_resolve_to_their_own() -> None:
    """Two files, one class name, two different models — and each file gets the right one.

    `"Customer"` is not an identity: the registry index keyed by class name is kept by whichever
    module registered LAST, which is bug #14 and does not fail, it describes the wrong table. What
    tells these two apart is the import line each file already wrote for its own checker. Nothing
    here asks any registry for a name.
    """
    from test.dto.homonyms.crm.models import Customer as CrmCustomer
    from test.dto.homonyms.shop.models import Customer as ShopCustomer

    shop = specs_in_source(_SHOP, path="shop/dto.py")
    crm = specs_in_source(_CRM, path="crm/dto.py")

    assert shop[0].model is ShopCustomer
    assert crm[0].model is CrmCustomer


def test_the_name_index_really_does_hold_only_one_of_them() -> None:
    """The premise of the test above, checked rather than trusted.

    Without this, the pair could be passing because the two models never collided at all, and it
    would go on passing if somebody rewrote the resolution to use the index. This asserts the trap
    is set: the global index answers `Customer` with exactly one of the two.
    """
    import test.dto.homonyms.crm.models  # noqa: F401
    import test.dto.homonyms.shop.models  # noqa: F401
    from snakeorm.registry import registry

    held = registry.table_by_name("Customer")
    registered = {
        table.name
        for model in registry.models()
        if (table := registry.table_of(model)) is not None
    }

    assert held is not None
    assert held.name in {"dto_shop_customers", "dto_crm_customers"}
    assert {"dto_shop_customers", "dto_crm_customers"} <= registered
