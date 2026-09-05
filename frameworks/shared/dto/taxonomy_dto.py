"""DTOs for the taxonomy domain (tag groups and tags). Flat and JSON-able."""

from __future__ import annotations

from collections.abc import Sequence

from shared.models import Tag, TagGroup


def group_dict(group: TagGroup) -> dict[str, object]:
    """A tag group as a dict."""
    return {"id": group.id, "name": group.name}


def tag_dict(tag: Tag) -> dict[str, object]:
    """A tag as a dict. `parent_id` is null for a root, which is where the taxonomy starts."""
    return {
        "id": tag.id,
        "name": tag.name,
        "group_id": tag.group_id,
        "parent_id": tag.parent_id,
    }


def tag_tree_dict(
    breadcrumb: Sequence[Tag], branch: Sequence[Tag]
) -> dict[str, object]:
    """A tag as a PLACE: the path from the root down to it, and everything hanging off it.

    The two halves travel in one document because they answer one question — where am I and what is
    under me — and a client that had to ask twice would draw a screen out of two moments of the
    taxonomy. The breadcrumb is ordered root first; the branch is the section, by name.
    """
    return {
        "breadcrumb": [tag_dict(tag) for tag in breadcrumb],
        "branch": [tag_dict(tag) for tag in branch],
    }
