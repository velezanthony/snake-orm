"""DRF serializers for the blog API: the SHAPE of the JSON objects, for drf-spectacular.

A SEAM (contrib): they re-declare the shape of the SnakeORM models (`User`, `Post`) in DRF's DSL,
because drf-spectacular introspects DRF serializers to generate the OpenAPI. It is the SAME `Post` as
in marshmallow (Flask) and Pydantic (FastAPI): candidate #1 for being derived from the ORM's metadata
graph.

DRF reads the SnakeORM model's attributes directly (as marshmallow does): `post.title`, and the
nested author through `post.author` (loaded by the `include`, with no N+1). The typed aggregate uses
a `source` with a path (`source="user.id"`).
"""

from __future__ import annotations

from rest_framework import serializers


class AuthorSerializer(serializers.Serializer):
    """The author nested inside a post (loaded by the selector's include)."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()


class PostSerializer(serializers.Serializer):
    """A post with its author nested."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField()
    published = serializers.BooleanField()
    author_id = serializers.IntegerField()
    # The counter the TRIGGER keeps. It has to be declared HERE as well as in `shared/dto/blog_dto`
    # because this endpoint serialises through DRF and the detail one goes through the DTO — one
    # resource with two descriptions of its shape, which is the seam this module's docstring already
    # names as candidate #1 for being derived from the metadata graph. Until it is, a field added to
    # one of them and not the other is a listing and a detail that disagree about what a post IS.
    visit_count = serializers.IntegerField()
    author = AuthorSerializer()


class UserStatsSerializer(serializers.Serializer):
    """A user with their post count (a typed aggregate: `row.user` + `row.post_count`)."""

    id = serializers.IntegerField(source="user.id")
    username = serializers.CharField(source="user.username")
    post_count = serializers.IntegerField()


# --- Envelopes -----------------------------------------------------------------------------------
# The API returns JSON OBJECTS, not top-level arrays: the ORM's debug envelope (the `envelope`
# channel) is injected INSIDE an object. Same seam as in Flask (C2 in the catalogue).


class PostsResponseSerializer(serializers.Serializer):
    """`{"posts": [...]}`."""

    posts = PostSerializer(many=True)


class UserStatsResponseSerializer(serializers.Serializer):
    """`{"users": [...]}`."""

    users = UserStatsSerializer(many=True)
