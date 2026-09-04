"""Routes of the taxonomy domain. The `/taxonomy/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.taxonomy import api

urlpatterns = [
    path("groups", api.list_groups, name="taxonomy_list_groups"),
    path("tags", api.tags, name="taxonomy_tags"),
    path("tags/<int:tag_id>/tree", api.tag_tree, name="taxonomy_tag_tree"),
    path("posts", api.filter_posts, name="taxonomy_filter_posts"),
    path("posts/<int:post_id>/tags", api.post_tags, name="taxonomy_post_tags"),
    path(
        "posts/<int:post_id>/tags/<int:tag_id>",
        api.untag_post,
        name="taxonomy_untag_post",
    ),
]
