"""Routes of the content PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split every domain with both already made:
`urls.py` is the API router mounted at `/api/content/`, and this one is the pages, mounted at
`/content/`.

TWO ROUTES. A revision and an attachment do not exist apart from the post that carries them, so
neither has a listing or a form of its own: the sheet of one post is where both are read and where
all three writes are submitted. There is no `create` page for the same reason there is no
`/content/revisions/` — a revision with no post is not a thing this domain can hold.

`detail/<int:post_id>/` takes a POST as well as a GET, which is where the page taxonomy bends the way
`taxonomy`, `logistics` and `engagement` bend it: a browser `<form>` emits only GET and POST, so the
three writes ride in the body under an `action` rather than being a POST and a DELETE on two
resources the way the API spells them.

The trailing slash stays — Django's convention, `APPEND_SLASH` redirects what arrives without one —
and the Flask mirror of these pages deliberately does not have it.
"""

from __future__ import annotations

from django.urls import path

from apps.content import views

urlpatterns = [
    path("list/", views.post_index, name="content_list"),
    path("detail/<int:post_id>/", views.post_content, name="content_detail"),
]
