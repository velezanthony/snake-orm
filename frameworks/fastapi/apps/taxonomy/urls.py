"""Router of the taxonomy domain (groups, tags and post tagging): a thin JSON API over the use cases.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from apps.deps import SessionDep, http_error
from apps.taxonomy import usecases
from apps.taxonomy.usecases import Failure
from shared.dto.blog_dto import PostDto, post_dict
from shared.dto.taxonomy_dto import group_dict, tag_dict, tag_tree_dict

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


class TagIn(BaseModel):
    """Body for creating a tag inside a group and, optionally, under another tag.

    `parent_id` defaults to nothing because a root is the ordinary case: most labels sit at the top
    of the taxonomy, and a body that demanded a parent would make a client invent one.
    """

    name: str
    group_id: int
    parent_id: int | None = None


class TagPostIn(BaseModel):
    """Body for tagging a post with a tag."""

    tag_id: int


@router.get("/groups")
async def list_groups(session: SessionDep) -> list[dict[str, object]]:
    """Every tag group."""
    return [group_dict(g) for g in await usecases.list_groups(session)]


@router.get("/tags")
async def list_tags(session: SessionDep) -> list[dict[str, object]]:
    """Every tag in the system."""
    return [tag_dict(t) for t in await usecases.list_tags(session)]


@router.get("/posts/{post_id}/tags")
async def tags_of_post(post_id: int, session: SessionDep) -> list[dict[str, object]]:
    """The tags of a post."""
    return [tag_dict(t) for t in await usecases.tags_of_post(session, post_id)]


@router.post("/tags", status_code=201)
async def create_tag(payload: TagIn, session: SessionDep) -> dict[str, object]:
    """Create a tag inside a group. 404 if the group does not exist."""
    result = await usecases.create_tag(
        session, payload.name, payload.group_id, payload.parent_id
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return tag_dict(result)


@router.get("/posts")
async def filter_posts(
    session: SessionDep, tags: str = "", without: int | None = None
) -> list[PostDto]:
    """Posts by tag. `?tags=1,2` carries ALL of them; adding `&without=3` subtracts that one.

    One route and two questions, because that is one screen: the tick boxes that narrow and the one
    that excludes. `without` is what decides which — with it the first tag is the base and the
    excluded one is taken off it; without it the tags are intersected and fewer than two is a 400,
    since "the posts of one tag" is a different question with an operation of its own.
    """
    tag_ids = [int(piece) for piece in tags.split(",") if piece.strip()]
    if without is not None:
        if not tag_ids:
            raise http_error(Failure("missing_fields"))
        posts = await usecases.posts_with_tag_but_not(session, tag_ids[0], without)
        return [post_dict(post) for post in posts]
    result = await usecases.posts_with_every_tag(session, tag_ids)
    if isinstance(result, Failure):
        raise http_error(result)
    return [post_dict(post) for post in result]


@router.post("/posts/{post_id}/tags", status_code=201)
async def tag_post(
    post_id: int, payload: TagPostIn, session: SessionDep, response: Response
) -> dict[str, object]:
    """Tag a post with a tag. 201 when this call created the link, 200 when it was already there.

    The decorator's `status_code` is the DEFAULT rather than the answer: it is what the schema at
    `/docs` advertises and what goes out when the link is new. Overwriting it on the response is how
    an idempotent POST tells a caller which of the two things happened.
    """
    _, created = await usecases.tag_post(session, post_id, payload.tag_id)
    if not created:
        response.status_code = 200
    return {"post_id": post_id, "tag_id": payload.tag_id}


@router.delete("/posts/{post_id}/tags/{tag_id}", status_code=204)
async def untag_post(post_id: int, tag_id: int, session: SessionDep) -> None:
    """Remove a tag from a post. 404 if that tagging did not exist."""
    result = await usecases.untag_post(session, post_id, tag_id)
    if isinstance(result, Failure):
        raise http_error(result)


@router.get("/tags/{tag_id}/tree")
async def tag_tree(tag_id: int, session: SessionDep) -> dict[str, object]:
    """Where a tag sits in the taxonomy and what hangs off it. 404 if the tag is not there.

    TWO statements whatever the depth, and the recursion is the SAME object the synchronous demos
    run: a `SnakeRecursive` has no colour, so the walk cannot drift into a second shape here.
    """
    breadcrumb = await usecases.tag_breadcrumb(session, tag_id)
    if isinstance(breadcrumb, Failure):
        raise http_error(breadcrumb)
    branch = await usecases.tag_descendants(session, tag_id)
    return tag_tree_dict(breadcrumb, branch)
