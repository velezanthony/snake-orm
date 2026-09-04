"""App routes: the SSR post CRUD and the canonical JSON API under `/api/`.

The auth PAGES are NOT here: they live in `apps/auth/web_urls.py`, which is the domain their
URLs said all along.
"""

from __future__ import annotations

from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.blog import api, views

urlpatterns = [
    # Post CRUD (gated by login).
    path("", views.post_list, name="post_list"),
    path("posts/new/", views.post_create, name="post_create"),
    path("posts/<int:post_id>/", views.post_detail, name="post_detail"),
    path("posts/<int:post_id>/edit/", views.post_edit, name="post_edit"),
    path("posts/<int:post_id>/delete/", views.post_delete, name="post_delete"),
    # Canonical JSON API of the blog (BFF), MIRROR of FastAPI/Flask: EVERYTHING under `/api/`, per resource.
    # `posts` (public reads, writes gated to the author) + `auth` (session by signed cookie).
    path("api/posts/", api.posts_list, name="api_posts_list"),
    path("api/posts/stats/", api.posts_stats, name="api_posts_stats"),
    path("api/posts/<int:post_id>/", api.post_detail, name="api_posts_detail"),
    path("api/auth/register/", api.auth_register, name="api_auth_register"),
    path("api/auth/login/", api.auth_login, name="api_auth_login"),
    path("api/auth/logout/", api.auth_logout, name="api_auth_logout"),
    # The route an SSR demo never needs and a client-routed one cannot work without: who the cookie
    # says you are. `apps/blog/api.auth_me` explains why it is a request and not a stored copy.
    path("api/auth/me/", api.auth_me, name="api_auth_me"),
    # OpenAPI + Swagger UI (drf-spectacular).
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
