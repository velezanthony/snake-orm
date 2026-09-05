"""Routes of the auth PAGES (SSR). The `/auth/` prefix comes from the root urls include.

The JSON side lives in `urls.py` next door, under `/api/auth/`: same domain, two surfaces.

FOUR ROUTES NOW, AND THE FOURTH IS THE DOMAIN'S FIRST REAL SCREEN. The three above it are the forms,
and they call the BLOG's use cases — which is why this domain looked as though it had pages while the
tokens and the sessions it is actually about had never been drawn. `access/<int:user_id>/` is the
ledger of both, and it READS: minting and revoking stay on `/api/auth/` with the argument this
repository already wrote down.

There is no section in the sidebar for these four. That is not an oversight: a sidebar of DOMAINS is
a table of contents for the demo's data, and the login, the sign-up and somebody's access ledger are
reached from the topbar and from that person's row in `accounts` — which is where a reader looking
for them would go.
"""

from __future__ import annotations

from django.urls import path

from apps.auth import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("access/<int:user_id>/", views.access, name="auth_access"),
]
