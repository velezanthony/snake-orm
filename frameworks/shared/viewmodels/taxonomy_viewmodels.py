"""taxonomy view models: the four pages of the tag domain — list, create, detail and filter.

The same four rules the other view models keep: go through the USE CASES and never a selector, return
a `TypedDict`, hand a `Failure` back untouched, and emit nothing but primitives so a template never
walks a relation. What this module adds is one distinction the other domains never had to make.

A FORM NOBODY HAS FILLED IN YET IS NOT A FAILURE. `posts_with_every_tag` refuses fewer than two tags,
and it is right to: an intersection of one branch is not an intersection, so answering would make the
operation's name stop describing its SQL. But the FILTER PAGE opens with nothing ticked, and that is
its ordinary first state — not a missing page. Turning the refusal into a `Failure` here would hand
the view an error where it needs a screen, so it becomes a field: `asked` says whether the engine was
put a question at all, and the tick boxes are rendered either way.

The two questions the screen can put are the reason the domain is here. Ticking two tags is an
`INTERSECT` — requiring both is a condition on two DIFFERENT bridge rows, so no `WHERE` expresses it
— and naming one to exclude is an `EXCEPT`. With something to subtract, ONE ticked tag is already a
question, which is why `asked` is not simply "two or more".

`checked` is what makes the detail page a screen rather than a list: the tags a post already carries
start ticked, and submitting the same box twice is precisely what used to leave two bridge rows for
one fact. The page is the reason `tag_post` had to become idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from snakeorm import SnakeSession

from shared.models import Post, Tag, TagGroup
from shared.usecases import taxonomy_usecases as usecases
from shared.usecases.result import Failure

# What the filter page says while nothing has been asked of the engine. It lives here and not in a
# template because the two demos draw one screen: two spellings of this sentence is how the pages
# start telling the reader two different things about the same state.
NOTHING_ASKED = (
    "Tick two tags to see the posts carrying BOTH of them, or tick one and pick a tag to "
    "exclude. One tag on its own is a different question, and the tag list answers it."
)


class TagRow(TypedDict):
    """One tag as a row: its id, its name and the group it hangs off."""

    id: int
    name: str
    group: str


class GroupRow(TypedDict):
    """One tag group with the tags under it. Empty groups included, on purpose."""

    id: int
    name: str
    tags: list[TagRow]


class TagListPage(TypedDict):
    """The landing page of the domain: every group, its tags, and how many there are in all."""

    groups: list[GroupRow]
    tag_count: int


class GroupChoice(TypedDict):
    """One option of the "new tag" form's group select."""

    id: int
    name: str


class TagFormPage(TypedDict):
    """The create form: the groups, the possible PARENTS, and the error of the last attempt."""

    groups: list[GroupChoice]
    parents: list[GroupChoice]
    error: str


class TagChoice(TypedDict):
    """One tick box: a tag, and whether it is already ticked on this screen."""

    id: int
    name: str
    group: str
    checked: bool


class PostTagsPage(TypedDict):
    """A post's tags as a screen: every tag offered, the carried ones ticked."""

    post_id: int
    title: str
    choices: list[TagChoice]
    carried: list[str]


class PostRow(TypedDict):
    """One post in the filter's result."""

    id: int
    title: str
    published: bool


class FilterPage(TypedDict):
    """The tag filter: the boxes, what was ticked, and what the engine answered — if it was asked."""

    choices: list[TagChoice]
    without: int | None
    excluded: str | None
    posts: list[PostRow]
    asked: bool
    hint: str


def _tag_row(tag: Tag, group_name: str) -> TagRow:
    """A tag flattened for a template. The group's NAME, so no template walks `tag.group`."""
    return {"id": tag.id, "name": tag.name, "group": group_name}


def _post_row(post: Post) -> PostRow:
    """A post flattened to the three things a result row shows."""
    return {"id": post.id, "title": post.title, "published": post.published}


def _groups_by_id(groups: Sequence[TagGroup]) -> dict[int, str]:
    """Group id to group name, so hanging a tag off its group costs no query per tag."""
    return {group.id: group.name for group in groups}


def tag_list(session: SnakeSession) -> TagListPage:
    """Every group with its tags. TWO statements, and neither grows with the number of groups.

    The tags arrive with their group already loaded (`list_tags` includes it), so the grouping is
    done here in one pass instead of asking once per group — which is the N+1 this page would be if
    it walked `group.tags` in a template.

    An EMPTY group is kept. It is where the create form sends a tag, and a group that disappeared
    from the list until somebody filled it would be a section of the screen that only exists once it
    stops being needed.
    """
    groups = usecases.list_groups(session)
    names = _groups_by_id(groups)
    tags = usecases.list_tags(session)
    by_group: dict[int, list[TagRow]] = {group.id: [] for group in groups}
    for tag in tags:
        by_group[tag.group_id].append(_tag_row(tag, names[tag.group_id]))
    return {
        "groups": [
            {"id": group.id, "name": group.name, "tags": by_group[group.id]}
            for group in groups
        ],
        "tag_count": len(tags),
    }


def tag_form(session: SnakeSession, *, error: str = "") -> TagFormPage:
    """The create form: the group, the optional PARENT, and whatever the last attempt complained about.

    The parent list is every existing tag, and it is OPTIONAL on the form for the same reason it is
    optional in the model: most labels are roots, and a form that forced a parent would make somebody
    invent one. It is what lets the tree be grown from the screen instead of only by the seeder — a
    `parent_id` no page can set is a column the demo describes and cannot demonstrate.

    The error travels through the page rather than through a flash, because the form is redrawn with
    the reason next to it and a flash would put it somewhere else on the screen.
    """
    return {
        "groups": [
            {"id": group.id, "name": group.name}
            for group in usecases.list_groups(session)
        ],
        "parents": [
            {"id": tag.id, "name": tag.name} for tag in usecases.list_tags(session)
        ],
        "error": error,
    }


def post_tags(session: SnakeSession, post_id: int) -> PostTagsPage:
    """One post's tags as tick boxes: every tag offered, the ones it carries already ticked.

    TWO statements — every tag, and this post's — and the ticking is a set membership in Python. The
    alternative is one `exists` per tag, which is a query per box on a screen whose whole point is
    that there are many boxes.
    """
    carried = usecases.tags_of_post(session, post_id)
    ticked = {tag.id for tag in carried}
    listing = tag_list(session)
    return {
        "post_id": post_id,
        "title": "",
        "choices": [
            {
                "id": tag["id"],
                "name": tag["name"],
                "group": tag["group"],
                "checked": tag["id"] in ticked,
            }
            for group in listing["groups"]
            for tag in group["tags"]
        ],
        "carried": [tag.name for tag in carried],
    }


def filtered_posts(
    session: SnakeSession, *, tag_ids: Sequence[int], without: int | None
) -> FilterPage:
    """The tag filter. `INTERSECT` for the ticked tags, `EXCEPT` when one is named to exclude.

    Which question gets asked is decided by `without`, and the asymmetry is real rather than a
    convenience: subtracting needs a base and something to take off it, so one ticked tag is already
    a question; requiring needs two things to require, so one is not.

    When neither shape is complete the engine is not asked ANYTHING, and the page says so. That is
    the screen's opening state, not an error — see this module's docstring.
    """
    listing = tag_list(session)
    every_tag = [tag for group in listing["groups"] for tag in group["tags"]]
    ticked = set(tag_ids)
    names = {tag["id"]: tag["name"] for tag in every_tag}
    choices: list[TagChoice] = [
        {
            "id": tag["id"],
            "name": tag["name"],
            "group": tag["group"],
            "checked": tag["id"] in ticked,
        }
        for tag in every_tag
    ]

    rows: list[Post] = []
    asked = False
    if without is not None and tag_ids:
        rows = usecases.posts_with_tag_but_not(session, tag_ids[0], without)
        asked = True
    elif without is None and len(tag_ids) >= 2:
        result = usecases.posts_with_every_tag(session, tag_ids)
        # The refusal cannot reach here — the branch above is the operation's own precondition — but
        # narrowing it is what keeps the union out of the return type instead of casting it away.
        if not isinstance(result, usecases.Failure):
            rows = result
            asked = True

    return {
        "choices": choices,
        "without": without,
        "excluded": names.get(without) if without is not None else None,
        "posts": [_post_row(post) for post in rows],
        "asked": asked,
        "hint": "" if asked else NOTHING_ASKED,
    }


class Crumb(TypedDict):
    """One step of the breadcrumb: the tag, and the link the template hangs off its id."""

    id: int
    name: str


class BranchRow(TypedDict):
    """One tag of the section under the current one, with how deep it hangs for the indent."""

    id: int
    name: str
    group: str
    depth: int


class TagTreePage(TypedDict):
    """A tag as a PLACE in the taxonomy: the path down to it, and everything hanging off it."""

    tag_id: int
    name: str
    group: str
    breadcrumb: list[Crumb]
    branch: list[BranchRow]
    leaf: bool


def _depths(rows: Sequence[Tag], root_id: int) -> dict[int, int]:
    """How deep each row hangs below the anchor, from the `parent_id` links the rows carry.

    A recursion answers with a SET and a section is drawn as an INDENT, so the level has to come
    from somewhere. It comes from the rows themselves: every one of them names the parent it was
    reached through, and the anchor is depth zero by definition.

    The walk is bounded by the number of rows rather than by the shape of the data, which is what
    keeps a `parent_id` somebody edited by hand from turning an indent into an infinite loop — the
    same failure `TREE_LIMIT` guards one storey down, at the point where it would cost a query
    instead of a cycle.
    """
    parents = {tag.id: tag.parent_id for tag in rows}
    depths: dict[int, int] = {root_id: 0}
    for tag in rows:
        chain: list[int] = []
        current: int | None = tag.id
        while current is not None and current not in depths and len(chain) <= len(rows):
            chain.append(current)
            current = parents.get(current)
        base = depths.get(current, 0) if current is not None else 0
        for step, identifier in enumerate(reversed(chain), start=1):
            depths[identifier] = base + step
    return depths


def tag_tree(session: SnakeSession, tag_id: int) -> TagTreePage | Failure:
    """Where a tag sits and what hangs off it: TWO statements, whatever the depth of the tree.

    One recursion climbs to the root and the other descends to the leaves, and neither grows a
    statement when the taxonomy grows a level — which is the whole reason the column exists. The
    page drawn without them is the same page at one query per level, twice.

    `not_found` travels untouched from the breadcrumb: a tag that is not there has no path, and the
    recursion that would have found the path is the one that says so.
    """
    breadcrumb = usecases.tag_breadcrumb(session, tag_id)
    if isinstance(breadcrumb, Failure):
        return breadcrumb
    here = breadcrumb[-1]
    groups = {group.id: group.name for group in usecases.list_groups(session)}
    branch = usecases.tag_descendants(session, tag_id)
    depths = _depths(branch, tag_id)
    return {
        "tag_id": here.id,
        "name": here.name,
        "group": groups.get(here.group_id, ""),
        "breadcrumb": [{"id": tag.id, "name": tag.name} for tag in breadcrumb],
        "branch": [
            {
                "id": tag.id,
                "name": tag.name,
                "group": groups.get(tag.group_id, ""),
                "depth": depths.get(tag.id, 1),
            }
            for tag in branch
        ],
        "leaf": not branch,
    }
