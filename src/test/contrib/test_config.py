"""Tests for the SHARED translators (`contrib.config`): dict → central config / (channels, panel).

The logic is generic (neither Django nor Flask): it translates the SHAPE of a `DATABASES`/`SNAKEORM`
into the typed objects. It recognizes both `"postgres"` and Django's `"django.db.backends.postgresql"`.
Everything fails loud.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from snakeorm.advisor import DEFAULT_MIN_MS
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.contrib.config import (
    SnakeOrmConfig,
    connection_from_mapping,
    debug_config_from_mapping,
    open_session,
)
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.debug import SnakeDebugChannel, SnakeDebugLanguage, capture_queries
from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.migration import autodetect, current_schema, render_migration
from snakeorm.registry import registry
from snakeorm.session import SnakeSession


def test_translates_the_connection_pieces() -> None:
    """It translates every piece of the connection dict into the central config's fields."""
    config = connection_from_mapping(
        {
            "ENGINE": "postgres",
            "NAME": "app",
            "HOST": "h",
            "PORT": "5433",
            "USER": "u",
            "PASSWORD": "p",
        }
    )
    assert config.backend is SnakeBackend.POSTGRES
    assert config.name == "app"
    assert config.host == "h"
    assert config.port == "5433"


def test_recognizes_the_django_engine_string() -> None:
    """It recognizes Django's `ENGINE` as is: whoever already has their `DATABASES` changes nothing."""
    config = connection_from_mapping(
        {"ENGINE": "django.db.backends.postgresql", "NAME": "x"}
    )
    assert config.backend is SnakeBackend.POSTGRES


def test_recognizes_the_sqlite_variants() -> None:
    """It accepts the three ways of naming SQLite (the short ones and Django's)."""
    for engine in ("sqlite", "sqlite3", "django.db.backends.sqlite3"):
        config = connection_from_mapping({"ENGINE": engine, "NAME": ":memory:"})
        assert config.backend is SnakeBackend.SQLITE


def test_unknown_engine_fails_loud() -> None:
    """An invalid `ENGINE` BLOWS UP naming it (fail loud), it does not fall back to a silent default."""
    with pytest.raises(
        SnakeConfigError, match="SnakeORM accepts: mysql, postgres, sqlite"
    ):
        connection_from_mapping({"ENGINE": "oracle", "NAME": "x"})


def test_debug_config_translates_channels_and_threshold() -> None:
    """The panel's config dict translates into channels + config (the advisor threshold)."""
    channels, config = debug_config_from_mapping(
        {"DEBUG": "ssr,timing", "ADVISE_MS": 25}
    )
    assert channels == frozenset({SnakeDebugChannel.SSR, SnakeDebugChannel.TIMING})
    assert config.advise_min_ms == 25.0


def test_debug_config_unknown_channel_fails_loud() -> None:
    """A channel with a typo BLOWS UP (fail loud): a debug that does not start up in silence is the failure to avoid."""
    with pytest.raises(
        SnakeConfigError, match="SNAKE_ORM_DEBUG accepts these channels"
    ):
        debug_config_from_mapping({"DEBUG": "ssr,bogus"})


def test_debug_config_bad_threshold_fails_loud() -> None:
    """A non-numeric `ADVISE_MS` BLOWS UP naming it, instead of swallowing it and falling back to a default."""
    with pytest.raises(SnakeConfigError, match="ADVISE_MS has to be a number, got"):
        debug_config_from_mapping({"DEBUG": "ssr", "ADVISE_MS": "diez"})  # type: ignore[typeddict-item]


def test_debug_config_defaults_when_keys_absent() -> None:
    """With no keys: empty channels (panel off) and our threshold. It does not blow up over absence."""
    channels, config = debug_config_from_mapping({})
    assert channels == frozenset()
    assert config.advise_min_ms == DEFAULT_MIN_MS


@snake_row
class _One(SnakeRow):
    """Minimal row to exercise a raw query in the capture test."""

    n: int


def test_open_session_opens_from_the_dataclass() -> None:
    """`open_session` opens a session from the central config DIRECTLY (the path with no binder)."""
    session = open_session(
        SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
    )
    assert isinstance(session, SnakeSession)
    session.close()


def test_open_session_feeds_the_debug_panel() -> None:
    """The session CAPTURES the SQL: the panel sees it (driver wrapped in CaptureDriver)."""
    with capture_queries() as collector:
        session = open_session(
            SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
        )
        session.raw("SELECT 1 AS n", into=_One)
        session.close()
    assert collector.report().count >= 1


def test_open_session_declares_the_engine_to_the_capture_driver() -> None:
    """Every captured record names the engine, which is what becomes `db.system.name` in a span.

    The declaration travels from the `backend` —the single place engine identity lives— through the
    capture driver. Without it the `otel` channel has no honest way to fill the one attribute Jaeger
    honest way to fill `db.system.name`, and would have to guess it from the driver's class or
    from the SQL — and neither can tell MySQL from MariaDB.
    """
    with capture_queries() as collector:
        session = open_session(
            SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
        )
        session.raw("SELECT 1 AS n", into=_One)
        session.close()

    assert {record.system for record in collector.report().records} == {"sqlite"}


def _root_config() -> SnakeOrmConfig:
    """The ROOT config with an in-memory SQLite connection and the panel configured."""
    return SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        },
        debug="ssr,envelope,timing",
        advise_ms=25,
    )


def test_root_config_opens_a_session_by_alias() -> None:
    """`SnakeOrmConfig.open()` opens the alias's connection (with capture for the panel)."""
    config = _root_config()
    with capture_queries() as collector:
        session = config.open()
        session.raw("SELECT 1 AS n", into=_One)
        session.close()
    assert collector.report().count >= 1


def test_root_config_exposes_channels_and_debug_config() -> None:
    """`SnakeOrmConfig` derives the panel channels and the advisor threshold from its fields."""
    config = _root_config()
    assert config.channels() == frozenset(
        {SnakeDebugChannel.SSR, SnakeDebugChannel.ENVELOPE, SnakeDebugChannel.TIMING}
    )
    assert config.debug_config().advise_min_ms == 25.0


def test_root_config_language_defaults_to_english() -> None:
    """With no language declared, the panel opens in English (the public tool's default)."""
    assert _root_config().language is SnakeDebugLanguage.EN
    assert _root_config().debug_config().language is SnakeDebugLanguage.EN


def test_root_config_language_flows_to_debug_config() -> None:
    """The language declared in the ROOT config flows into the `SnakeDebugConfig` the panel consumes."""
    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        },
        debug="ssr",
        language=SnakeDebugLanguage.ES,
    )
    assert config.debug_config().language is SnakeDebugLanguage.ES


def test_root_config_defaults_are_sane() -> None:
    """With neither `debug` nor `advise_ms`: panel off (empty channels) and our threshold."""
    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        }
    )
    assert config.channels() == frozenset()
    assert config.debug_config().advise_min_ms == DEFAULT_MIN_MS


def test_root_config_bad_channel_fails_loud() -> None:
    """A channel with a typo in `debug` BLOWS UP when the channels are asked for (fail loud)."""
    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        },
        debug="ssr,bogus",
    )
    with pytest.raises(
        SnakeConfigError, match="SNAKE_ORM_DEBUG accepts these channels"
    ):
        config.channels()


def test_root_config_migrations_dir_optional_default_none() -> None:
    """`migrations_dir` is optional: `None` by default (per-domain mode; the value IS the flag)."""
    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        }
    )
    assert config.migrations_dir is None


def test_root_config_migrate_per_domain_without_migrations_fails_loud() -> None:
    """`migrate()` in per-domain mode (`migrations_dir=None`) with no `apps/*/migrations` BLOWS UP clearly."""
    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        }
    )
    with pytest.raises(SnakeConfigError, match="Generate the ones for each domain"):
        config.migrate()  # the tests' cwd: there is no apps/*/migrations


def test_root_config_migrate_builds_the_schema_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SnakeOrmConfig.migrate()` applies the migrations and BUILDS the schema on SQLite —MULTI-ENGINE,
    right where the CLI (tied to Postgres) does not reach—: the backend picks driver+dialect on its own."""
    # Isolated registry: only our model goes into the migration.
    for attr in ("_tables", "_by_name", "_model_by_name", "_table_owner"):
        monkeypatch.setattr(registry, attr, {})
    (tmp_path / "mig_model.py").write_text(
        "from snakeorm.decorators import snake_model\n"
        "from snakeorm.fields import SnakeColumn, snake_auto, snake_str\n"
        "from snakeorm.model import SnakeModel\n\n"
        "@snake_model(table='widgets')\n"
        "class Widget(SnakeModel):\n"
        "    id: SnakeColumn[int] = snake_auto()\n"
        "    name: SnakeColumn[str] = snake_str()\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.import_module("mig_model")

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    operations = autodetect([], current_schema())
    (mig_dir / "0001_initial.py").write_text(
        render_migration("0001_initial", operations)
    )

    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=str(tmp_path / "app.sqlite")
            )
        },
        migrations_dir=str(mig_dir),
    )
    assert config.migrate() == ["0001_initial"]  # it applied the migration on SQLite

    # The schema EXISTS: a query against the created table does not blow up (empty, but it exists).
    driver, _dialect = config.databases["default"].driver_and_dialect()
    try:
        assert driver.fetch_all("SELECT COUNT(*) FROM widgets", ()) == [(0,)]
    finally:
        driver.close()


def test_open_names_the_connections_it_has_when_the_alias_is_wrong() -> None:
    """A mistyped alias gets a `SnakeError` naming the alias AND the ones that exist.

    It used to be `self.databases[alias]` bare: a `KeyError: 'analitycs'` that does not say what
    aliases there are, does not say where they are declared, and is not even a `SnakeError` — so an
    application catching `SnakeError` around its own start-up did not catch it.

    The ORM already knows how to answer this. `_backend_for` twelve lines below refuses an unknown
    ENGINE naming the valid ones, with "fail loud: a typo never falls back to a default" written on
    it. Three places, one question, two qualities of answer.
    """
    sqlite = SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
    config = SnakeOrmConfig(databases={"default": sqlite, "reporting": sqlite})

    with pytest.raises(SnakeConfigError) as caught:
        config.open("analitycs")

    message = str(caught.value)
    assert "analitycs" in message, "it does not say what the user typed"
    assert "default" in message and "reporting" in message, (
        "it does not say what the user could have typed"
    )


def test_migrate_checks_the_alias_before_loading_a_single_migration() -> None:
    """The alias is validated FIRST, not after the whole migration history is discovered and sorted.

    The lookup sat at the end, so a typo in an argument cost a full directory walk and a topological
    sort before failing — and the failure was still a bare `KeyError`.
    """
    sqlite = SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
    config = SnakeOrmConfig(
        databases={"default": sqlite}, migrations_dir="does-not-exist"
    )

    with pytest.raises(SnakeConfigError, match="nope"):
        config.migrate("nope")
