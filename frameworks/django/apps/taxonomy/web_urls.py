"""Routes of the taxonomy PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split `apps/auth/`, `apps/inventory/`,
`apps/orders/` and `apps/billing/` already made: `urls.py` is the API router mounted at
`/api/taxonomy/`, and this one is the pages, mounted at `/taxonomy/`.

FIVE ROUTES AND NOT SEVEN, and the two that are missing are the domain's statement. There is no
`update/` and no `delete/` of a tag: a tag is a NAME that rows point at, so renaming one rewrites the
meaning of every post already carrying it, and deleting one silently unfiles them. Neither is a thing
a demo should teach with a form, and `shared/web/nav.py` says so in the catalogue.

`detail/<int:post_id>/` takes a POST as well as a GET, which is the one place in this module where
the taxonomy of pages bends: a browser `<form>` emits only GET and POST, so ticking a box is a POST
to the page that shows the boxes rather than a `POST`/`DELETE` on a tag resource the way the API
does it. The action rides in the body, and the API mirror of it is two routes.

The trailing slash stays — Django's convention, `APPEND_SLASH` redirects what arrives without one —
and the Flask mirror of these pages deliberately does not have it.
"""

from __future__ import annotations

from django.urls import path

from apps.taxonomy import views

urlpatterns = [
    path("list/", views.tag_list, name="taxonomy_list"),
    path("create/", views.tag_create, name="taxonomy_create"),
    path("detail/<int:post_id>/", views.post_tags, name="taxonomy_detail"),
    path("filter/", views.filter_posts, name="taxonomy_filter"),
    path("tree/<int:tag_id>/", views.tag_tree, name="taxonomy_tree"),
]
