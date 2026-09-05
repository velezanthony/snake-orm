"""Routes of the engagement domain. The `/engagement/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.engagement import api

urlpatterns = [
    path(
        "posts/<int:post_id>/comments",
        api.post_comments,
        name="engagement_post_comments",
    ),
    path(
        "posts/<int:post_id>/reactions",
        api.post_reactions,
        name="engagement_post_reactions",
    ),
    path("posts/<int:post_id>/visits", api.post_visits, name="engagement_post_visits"),
    path("visits/export", api.visits_export, name="engagement_visits_export"),
]
