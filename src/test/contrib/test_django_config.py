"""Tests for the Django binder: `django_session` reads Django's NATIVE `DATABASES`.

The dict translation is tested by `test_config.py` (it is generic); here only what is Django-specific:
reading from `DATABASES`. `django_session` accepts the mapping injected (the project's pattern) so it
can be tested WITHOUT configuring Django globally.
"""

from __future__ import annotations

from snakeorm.connection import SnakeBackend
from snakeorm.contrib.config import SnakeOrmConfig
from snakeorm.contrib.django import config_from_django, django_session
from snakeorm.debug import SnakeDebugChannel, capture_queries
from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.session import SnakeSession


@snake_row
class _One(SnakeRow):
    """Minimal row to exercise a raw query in the capture tests."""

    n: int


def test_django_session_reads_the_databases_mapping() -> None:
    """`django_session` opens a session reading from `DATABASES` (injected, without configuring Django)."""
    session = django_session(
        "default", databases={"default": {"ENGINE": "sqlite", "NAME": ":memory:"}}
    )
    assert isinstance(session, SnakeSession)
    session.close()


def test_django_session_feeds_the_debug_panel() -> None:
    """The binder's session CAPTURES the SQL: the panel sees it (driver wrapped in CaptureDriver)."""
    with capture_queries() as collector:
        session = django_session(
            databases={"default": {"ENGINE": "sqlite", "NAME": ":memory:"}}
        )
        session.raw("SELECT 1 AS n", into=_One)
        session.close()
    assert collector.report().count >= 1


def test_config_from_django_converges_on_the_root_config() -> None:
    """Django translates its DATABASES + SNAKEORM into the SAME `SnakeOrmConfig` Flask/FastAPI build."""
    config = config_from_django(
        databases={"default": {"ENGINE": "postgres", "NAME": "app", "HOST": "h"}},
        snakeorm={"DEBUG": "ssr,timing", "ADVISE_MS": 25},
    )
    assert isinstance(config, SnakeOrmConfig)
    assert config.databases["default"].backend is SnakeBackend.POSTGRES
    assert config.databases["default"].name == "app"
    assert config.channels() == frozenset(
        {SnakeDebugChannel.SSR, SnakeDebugChannel.TIMING}
    )
    assert config.debug_config().advise_min_ms == 25.0
