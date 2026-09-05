"""Dependent VIEWS against a real Postgres: `depends_on` orders the CREATE/DROP in the migration.

E2E scenario with UNIQUE names (`vo_*`): a real table, a view A that reads from it and a view B that
reads from A (`depends_on=[A]`). The migration is GENERATED with the diff (which sorts topologically)
and applied with the runner: if the order were wrong, `CREATE VIEW B` would fail before A existed. It
is checked in `information_schema.views` that both views exist; the rollback deletes them in REVERSE
order (B first, the one that depends) with no dependency error.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model, snake_view
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.migration import Migration, MigrationRunner, diff_schema
from snakeorm.model import SnakeModel, SnakeView
from snakeorm.registry import registry
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="vo_events")
class VoEvent(SnakeModel):
    """Real events table: the base the chain of views hangs off."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    kind: SnakeColumn[str] = snake_str()


@snake_view(
    sql="SELECT kind AS kind, count(*)::int AS total FROM vo_events GROUP BY kind",
    name="vo_event_counts",
)
class VoEventCounts(SnakeView):
    """View A: aggregates the events by kind (reads from the TABLE)."""

    kind: SnakeColumn[str] = snake_str()
    total: SnakeColumn[int] = snake_int()


@snake_view(
    sql="SELECT kind AS kind, total AS total FROM vo_event_counts WHERE total > 0",
    name="vo_busy_kinds",
    depends_on=[VoEventCounts],
)
class VoBusyKinds(SnakeView):
    """View B: filters view A (reads from ANOTHER view) → it must be created AFTER A."""

    kind: SnakeColumn[str] = snake_str()
    total: SnakeColumn[int] = snake_int()


def _view_exists(driver: PsycopgDriver, name: str) -> bool:
    """Queries information_schema.views to find out whether the view exists in the public schema."""
    rows = driver.fetch_all(
        "SELECT COUNT(*) FROM information_schema.views "
        "WHERE table_schema = 'public' AND table_name = %s",
        (name,),
    )
    return bool(rows[0][0])


def _migration() -> Migration:
    """Generates the migration for the three pieces (table + two views) with the diff that orders them."""
    pieces = [
        registry.table_of(VoEvent),
        registry.table_of(VoEventCounts),
        registry.table_of(VoBusyKinds),
    ]
    operations = diff_schema(
        [], [p for p in pieces if p is not None], registry.table_by_name
    )
    return Migration(version="vo_it_0001", operations=tuple(operations))


def test_dependent_views_apply_and_rollback_in_order() -> None:
    """The generated migration creates A before B (applies with no error) and the rollback deletes them backwards."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    driver = PsycopgDriver(connection)
    runner = MigrationRunner(driver, PostgresDialect())
    migration = _migration()
    try:
        driver.execute("DROP VIEW IF EXISTS vo_busy_kinds", ())
        driver.execute("DROP VIEW IF EXISTS vo_event_counts", ())
        driver.execute("DROP TABLE IF EXISTS vo_events CASCADE", ())
        driver.commit()

        # Apply: if the order were wrong, CREATE VIEW vo_busy_kinds would fail (A would not exist).
        runner.apply([migration])
        assert _view_exists(driver, "vo_event_counts") is True
        assert _view_exists(driver, "vo_busy_kinds") is True

        # Rollback: deletes B (the one that depends) before A, with no dependency error.
        runner.rollback(migration)
        assert _view_exists(driver, "vo_event_counts") is False
        assert _view_exists(driver, "vo_busy_kinds") is False
    finally:
        driver.execute("DROP VIEW IF EXISTS vo_busy_kinds", ())
        driver.execute("DROP VIEW IF EXISTS vo_event_counts", ())
        driver.execute("DROP TABLE IF EXISTS vo_events CASCADE", ())
        driver.execute(
            "DELETE FROM public.snake_migrations WHERE version = 'vo_it_0001'", ()
        )
        driver.commit()
        driver.close()
