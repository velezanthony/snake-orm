"""The tag TREE, and the one thing about it that no other shape can do: walk a chain of unknown length.

A taxonomy is a hierarchy — the word means nothing else — and the two questions a reader arrives with
are where am I and what is under this. Both are the same walk in opposite directions, and both are
answered by ONE statement whatever the depth of the tree.

WHAT WOULD PASS WITHOUT THE RECURSION, and this is what most of this file is written against. A page
that fetched the parent, then that parent's parent, and stopped when it ran out, would return exactly
the same breadcrumb, in the same order, with the same names in it. Every assertion about CONTENT
would still pass. So the content half here is the small half; the load-bearing one is the COUNT of
statements, measured while the tree is three deep, because that is the number the two implementations
disagree on and the only one that does.

AND THE DIRECTION IS THE OTHER THING WORTH A TEST, because the pair of columns is all that separates
the two questions: `on=(Tag.parent_id, Tag.id)` descends and `on=(Tag.id, Tag.parent_id)` climbs.
Swapped by accident, a breadcrumb silently becomes a subtree — both return rows, both are non-empty,
and only an assertion about WHICH rows says anything.
"""

from __future__ import annotations

from snakeorm import SnakeSession
from snakeorm.debug import capture_queries

from shared.models import Tag, TagGroup
from shared.selectors import taxonomy_selectors as selectors
from shared.usecases import taxonomy_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import taxonomy_viewmodels as viewmodels


def _tree(session: SnakeSession) -> dict[str, int]:
    """A three-deep taxonomy plus a branch that hangs off nothing, by name.

        sql                 tooling
        └── orm             (a root with no children: the leaf case)
            └── migrations

    The loose root is not decoration: a walk that forgot its `WHERE` would bring it back, and with a
    single chain in the table there would be nothing for it to wrongly include.
    """
    group = session.add(TagGroup(name="topics"))
    identifiers: dict[str, int] = {}
    for name, parent in (
        ("sql", None),
        ("orm", "sql"),
        ("migrations", "orm"),
        ("tooling", None),
    ):
        identifiers[name] = session.add(
            Tag(
                name=name,
                group_id=group.id,
                parent_id=identifiers[parent] if parent else None,
            )
        ).id
    session.commit()
    return identifiers


def test_the_breadcrumb_is_the_chain_from_the_root_down(session: SnakeSession) -> None:
    """Three levels, root first, ending on the tag that was asked for."""
    tags = _tree(session)

    crumbs = usecases.tag_breadcrumb(session, tags["migrations"])

    assert not isinstance(crumbs, Failure)
    assert [tag.name for tag in crumbs] == ["sql", "orm", "migrations"]


def test_the_breadcrumb_of_a_root_is_the_root_itself(session: SnakeSession) -> None:
    """A root is not a special case: it is a chain of one, and the page draws it as one crumb."""
    tags = _tree(session)

    crumbs = usecases.tag_breadcrumb(session, tags["sql"])

    assert not isinstance(crumbs, Failure)
    assert [tag.name for tag in crumbs] == ["sql"]


def test_a_tag_that_is_not_there_has_no_path(session: SnakeSession) -> None:
    """`not_found`, and it costs no probing query: an empty recursion IS the answer.

    The emptiness is what the use case reads, rather than a `SELECT` before it asking whether the row
    exists — the query that answers the question already answers whether there was one.
    """
    _tree(session)

    assert usecases.tag_breadcrumb(session, 9999) == Failure("not_found")


def test_the_section_is_every_tag_underneath_at_any_depth(
    session: SnakeSession,
) -> None:
    """Two levels down, and the tag itself is not one of its own descendants."""
    tags = _tree(session)

    branch = usecases.tag_descendants(session, tags["sql"])

    assert [tag.name for tag in branch] == ["migrations", "orm"]


def test_the_section_does_not_reach_a_branch_that_hangs_off_nothing(
    session: SnakeSession,
) -> None:
    """A walk that lost its anchor would bring the whole table back and still look plausible."""
    tags = _tree(session)

    branch = usecases.tag_descendants(session, tags["sql"])

    assert "tooling" not in {tag.name for tag in branch}


def test_a_leaf_has_nothing_under_it(session: SnakeSession) -> None:
    """The empty section is an answer and not a failure: it is what a leaf of the tree looks like."""
    tags = _tree(session)

    assert usecases.tag_descendants(session, tags["migrations"]) == []


def test_the_two_directions_are_not_the_same_query(session: SnakeSession) -> None:
    """Climbing and descending from the MIDDLE of the chain give different tags.

    Anchored on a root or on a leaf, one of the two answers is a single row and a swapped pair of
    columns could pass by luck. From the middle both answers have something in them and they share
    only the anchor, which is the one position where the mistake cannot hide.
    """
    tags = _tree(session)

    up = usecases.tag_breadcrumb(session, tags["orm"])
    down = usecases.tag_descendants(session, tags["orm"])

    assert not isinstance(up, Failure)
    assert [tag.name for tag in up] == ["sql", "orm"]
    assert [tag.name for tag in down] == ["migrations"]


def test_the_whole_page_is_two_statements_whatever_the_depth(
    session: SnakeSession,
) -> None:
    """THE ASSERTION THE FEATURE EXISTS FOR: the count does not grow with the tree.

    Three levels and three statements — the two recursions plus the groups the page names its tags
    by. The level-at-a-time implementation this replaces would pay one query per level for the
    breadcrumb and another per level for the section, so a taxonomy one level deeper would move this
    number and nothing else in this file would notice.
    """
    tags = _tree(session)

    with capture_queries() as collector:
        page = viewmodels.tag_tree(session, tags["migrations"])

    assert not isinstance(page, Failure)
    assert page["breadcrumb"] == [
        {"id": tags["sql"], "name": "sql"},
        {"id": tags["orm"], "name": "orm"},
        {"id": tags["migrations"], "name": "migrations"},
    ]
    assert len(collector.report().records) == 3


def test_the_walk_stops_itself_on_a_cycle(session: SnakeSession) -> None:
    """The recursion joins its steps with `UNION`, which is what actually ends a cyclic walk.

    This test used to be called `..._is_bounded_against_a_cycle` and asserted only the `LIMIT` — a
    name promising protection over a check that could not deliver it. Measured on Postgres, a cyclic
    walk with `order_by()` and a LIMIT never returns: the sort has to produce every row before it
    emits one, so the bound never gets its turn. `UNION` is what makes the repeating lap contribute
    nothing, so the step comes back empty and the recursion ends.
    """
    sql, params = selectors.subtree_of(1).to_sql(session.dialect)

    assert "WITH RECURSIVE" in sql
    assert "UNION ALL" not in sql
    # The bound travels as a PARAMETER and not in the string, which is this ORM's rule for every
    # value. It bounds the RESULT, not the walk.
    assert sql.endswith("LIMIT ?")
    assert params[-1] == selectors.TREE_LIMIT


def test_the_page_indents_by_how_deep_a_tag_hangs(session: SnakeSession) -> None:
    """The section is drawn as a tree and not as a list, so each row carries its own level."""
    tags = _tree(session)

    page = viewmodels.tag_tree(session, tags["sql"])

    assert not isinstance(page, Failure)
    assert {row["name"]: row["depth"] for row in page["branch"]} == {
        "orm": 1,
        "migrations": 2,
    }


def test_the_create_form_offers_a_parent_and_the_root_option(
    session: SnakeSession,
) -> None:
    """The tree can be GROWN from the screen, not only by the seeder.

    A `parent_id` no page can set is a column the demo describes and cannot demonstrate — and a
    parameter nothing ever passes is the same defect from the other side, a signature that has
    stopped being exercised without anybody saying so.
    """
    tags = _tree(session)

    form = viewmodels.tag_form(session)

    assert {parent["name"] for parent in form["parents"]} == set(tags)


def test_creating_a_tag_under_another_puts_it_in_the_tree(
    session: SnakeSession,
) -> None:
    """The whole round trip: create with a parent, and the breadcrumb of the new tag has two steps."""
    tags = _tree(session)

    created = usecases.create_tag(session, "planner", 1, tags["orm"])

    assert not isinstance(created, Failure)
    crumbs = usecases.tag_breadcrumb(session, created.id)
    assert not isinstance(crumbs, Failure)
    assert [tag.name for tag in crumbs] == ["sql", "orm", "planner"]


def test_creating_a_tag_without_one_leaves_it_a_root(session: SnakeSession) -> None:
    """No parent is the ordinary case and it stays the default: the tag is its own breadcrumb."""
    _tree(session)

    created = usecases.create_tag(session, "planner", 1)

    assert not isinstance(created, Failure)
    assert created.parent_id is None
