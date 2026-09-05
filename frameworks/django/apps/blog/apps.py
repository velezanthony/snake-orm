"""App config: on startup it recreates the SnakeORM schema and seeds the shared data."""

from __future__ import annotations

from django.apps import AppConfig


class BlogConfig(AppConfig):
    name = "apps.blog"

    def ready(self) -> None:
        """Reset + seed on startup (idempotent thanks to the reset: always the same initial state)."""
        from apps.blog import seed

        seed.reset_and_seed()
