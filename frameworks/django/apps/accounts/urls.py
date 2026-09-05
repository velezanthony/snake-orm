"""Routes of the accounts domain (roles). The `/accounts/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.accounts import api

urlpatterns = [
    path("roles", api.roles, name="accounts_roles"),
    path("users/<int:user_id>/roles", api.user_roles, name="accounts_user_roles"),
    path(
        "users/<int:user_id>/roles/<int:role_id>",
        api.revoke_role,
        name="accounts_revoke_role",
    ),
]
