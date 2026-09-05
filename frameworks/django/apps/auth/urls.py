"""Routes of the auth domain (tokens/sessions). The `/auth/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.auth import api

urlpatterns = [
    path(
        "users/<int:user_id>/tokens/active",
        api.active_tokens,
        name="auth_active_tokens",
    ),
    path("users/<int:user_id>/tokens", api.user_tokens, name="auth_user_tokens"),
    path(
        "users/<int:user_id>/sessions",
        api.sessions_of_user,
        name="auth_sessions_of_user",
    ),
    path("tokens/<int:token_id>", api.revoke_token, name="auth_revoke_token"),
]
