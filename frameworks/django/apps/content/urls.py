"""Routes of the content domain. The `/content/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.content import api

urlpatterns = [
    path(
        "posts/<int:post_id>/revisions",
        api.post_revisions,
        name="content_post_revisions",
    ),
    path(
        "posts/<int:post_id>/history",
        api.post_history,
        name="content_post_history",
    ),
    path(
        "posts/<int:post_id>/attachments",
        api.post_attachments,
        name="content_post_attachments",
    ),
    path(
        "attachments/<int:attachment_id>",
        api.remove_attachment,
        name="content_remove_attachment",
    ),
]
