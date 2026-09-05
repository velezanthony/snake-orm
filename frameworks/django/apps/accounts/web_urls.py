"""Routes of the accounts PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split every domain with both already made:
`urls.py` is the API router mounted at `/api/accounts/`, and this one is the pages, mounted at
`/accounts/`.

TWO ROUTES, and the absences are the domain's statement rather than three forms nobody wrote. There
is no `update` and no `delete` of a role: a role is a NAME that grants point at, so renaming one
rewrites what every holder of it is entitled to and deleting one silently strips them — the same
argument `taxonomy` makes about a tag, and the API offers neither operation either.

The creation form lives ON the listing instead of on a `create` page of its own. A role is a name and
nothing else, so a whole screen to type one would be a page with a single field on it, and the
listing is where a reader can see the names already taken while typing the next one.

`detail/<int:user_id>/` takes a POST as well as a GET, which is where the page taxonomy bends the way
`taxonomy` bends it: a browser `<form>` emits only GET and POST, so granting and withdrawing ride in
the body under an `action` rather than being a POST and a DELETE the way the API spells them.

The trailing slash stays — Django's convention, `APPEND_SLASH` redirects what arrives without one —
and the Flask mirror of these pages deliberately does not have it.
"""

from __future__ import annotations

from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("list/", views.role_directory, name="accounts_list"),
    path("detail/<int:user_id>/", views.user_roles, name="accounts_detail"),
]
