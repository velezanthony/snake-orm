"""Marshmallow schemas of the blog API: the SHAPE of the JSON objects, for flask-smorest.

SEAM (contrib): these schemas RE-DECLARE, in marshmallow's DSL, the shape of the SnakeORM models
(`User`, `Post`), because flask-smorest only understands marshmallow for generating the OpenAPI and
validating. That shape ALREADY lives in the ORM's metadata graph (`SnakeColumnInfo`: name, type,
nullable); here it is written out a second time. It is candidate #1 for automation via a
`snake_to_marshmallow(Model)` that derives it from the model.

Marshmallow reads the SnakeORM model's attributes directly (getattr): `post.title`, and for the
nested author, `post.author` -which comes loaded by the `include`, so it does NOT fire an N+1-.
"""

from __future__ import annotations

from marshmallow import Schema, fields


class AuthorSchema(Schema):
    """The author nested inside a post (loaded by the selector's include, no N+1)."""

    id = fields.Int()
    username = fields.Str()
    email = fields.Str()


class PostSchema(Schema):
    """A post with its author nested."""

    id = fields.Int()
    title = fields.Str()
    body = fields.Str()
    published = fields.Bool()
    author_id = fields.Int()
    # The counter the TRIGGER keeps, declared here for the same reason Django declares it in its
    # DRF serializer: this endpoint serialises through marshmallow while the rest of the demo goes
    # through `shared/dto/blog_dto`, so one resource has two descriptions of its shape. FastAPI has
    # only one — it hands the DTO straight back — which is why it needed no change at all.
    visit_count = fields.Int()
    author = fields.Nested(AuthorSchema)


class UserStatsSchema(Schema):
    """A user with their post count (a typed ORM aggregate: `row.user` + `row.post_count`)."""

    id = fields.Int(attribute="user.id")
    username = fields.Str(attribute="user.username")
    post_count = fields.Int()


# --- Envelopes -----------------------------------------------------------------------------------
# The API returns JSON OBJECTS, not top-level arrays: the ORM's debug envelope (the `envelope` channel)
# is injected INSIDE an object. SEAM: smorest's REST idiom would prefer naked arrays (with
# X-Pagination); here they are wrapped in `{...}` so the debug tooling can add `snakeorm`.


class PostsResponse(Schema):
    """`{"posts": [...]}`."""

    posts = fields.List(fields.Nested(PostSchema))


class UserStatsResponse(Schema):
    """`{"users": [...]}`."""

    users = fields.List(fields.Nested(UserStatsSchema))
