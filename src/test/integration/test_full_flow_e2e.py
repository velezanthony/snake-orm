"""INTEGRATION: the COMPLETE flow, end to end, with the `examples/shop` domain.

This test exists because the six phases each have green tests on their own and NOBODY had used
them together. Here we walk the real path of a project:

    models → autodetect → render_migration → FILE on disk → load() → MigrationRunner.apply()
    → insert → query → concurrency → rollback

It goes through the migration file on purpose, instead of applying the operations in memory: the
renderer is where a bug has hidden the most times in this branch, and `exec` of the generated file
is the only way to check that what was written can be read back.

And it uses TWO databases from the SAME container: the second connection does not need another
server, just another database.

It skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

from snakeorm.core.exceptions import SnakeCheckViolation
import pytest

from test.conftest import NO_SERVER_REASON

from examples.shop.models import Customer, OrderStatus, Order, Priority, Visit
from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeQuery,
    SnakeSession,
    snake_link,
    snake_table,
)
from snakeorm.core.config import dsn_for
from snakeorm.migration import (
    Migration,
    MigrationRunner,
    autodetect,
    current_schema,
    load,
    render_migration,
)
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_TABLES = ("shop_orders", "shop_customers")


def _clean(driver: PsycopgDriver) -> None:
    """Leaves the database with no trace of the example (and no migration history)."""
    for table in _TABLES:
        driver.execute(f"DROP TABLE IF EXISTS {table} CASCADE", ())
    # The pattern goes PARAMETERIZED: psycopg2 treats the `%` of the LIKE as a placeholder marker
    # even if you pass no parameters, and blows up with a most cryptic IndexError.
    driver.execute("DELETE FROM snake_migrations WHERE version LIKE %s", ("%shop%",))
    driver.commit()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session against the default connection, with the example domain linked."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    snake_link()
    MigrationRunner(driver, PostgresDialect()).ensure_tracking_table()
    _clean(driver)
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        _clean(driver)
        driver.close()


def _migrate(session: SnakeSession, target: Path) -> list[Migration]:
    """Generates the domain migration, WRITES it, reads it back and applies it.

    The trip through disk is the point: it checks that what the renderer writes can be imported
    again and produces the same operations.
    """
    tables = [
        t for t in current_schema(database="default") if t.name.startswith("shop_")
    ]
    operations = autodetect([], tables)
    assert operations, "the example domain should produce operations"

    target.mkdir(parents=True, exist_ok=True)
    (target / "0001_shop.py").write_text(render_migration("0001_shop", operations))

    migrations = load(target)
    MigrationRunner(session._driver, PostgresDialect()).apply(migrations)  # noqa: SLF001
    return migrations


def test_the_whole_chain_from_models_to_a_working_schema(
    session: SnakeSession, tmp_path: Path
) -> None:
    """THE FLOW: models → migration on disk → applied → real tables that accept rows."""
    _migrate(session, tmp_path / "migrations")

    client = session.add(Customer(email="ana@x.com", name="Ana", baja=None))
    session.commit()

    session.add(
        Order(
            customer_id=client.id,
            status=OrderStatus.PAID,
            priority=Priority.URGENT,
            amount=Decimal("19.99"),
        )
    )
    session.commit()

    found = session.first(SnakeQuery(Order).filter(Order.status == OrderStatus.PAID))
    assert found is not None
    assert found.status is OrderStatus.PAID, "the enum comes back as a member"
    assert found.amount == Decimal("19.99")
    assert found.created is not None, (
        "the server_default filled it in and it came back through RETURNING"
    )


def test_every_declared_object_reached_the_database(
    session: SnakeSession, tmp_path: Path
) -> None:
    """Checks in the CATALOG that EVERYTHING arrived: checks, partial index and comments.

    This is the verification no phase did on its own: each one tested its piece, but nobody looked
    at whether the whole thing lands intact in a real database.
    """
    _migrate(session, tmp_path / "migrations")
    driver = session._driver  # noqa: SLF001

    checks = {
        str(row[0])
        for row in driver.fetch_all(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'shop_orders'::regclass "
            "AND contype = 'c'",
            (),
        )
    }
    assert "ck_shop_orders_amount_positive" in checks
    assert "ck_shop_orders_status" in checks, "the CHECK derived from the enum"

    partials = driver.fetch_all(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_shop_customers_activos'",
        (),
    )
    assert partials and "WHERE" in str(partials[0][0]), (
        "the PARTIAL index with its condition"
    )

    comment = driver.fetch_all("SELECT obj_description('shop_customers'::regclass)", ())
    assert comment[0][0] == "Customers registered in the store"


def test_the_database_rejects_what_the_model_forbids(
    session: SnakeSession, tmp_path: Path
) -> None:
    """Checks that the model rules are enforced by the ENGINE, not by Python."""

    _migrate(session, tmp_path / "migrations")
    client = session.add(Customer(email="ana@x.com", name="Ana", baja=None))
    session.commit()

    with pytest.raises(SnakeCheckViolation, match="CHECK constraint"):
        session._driver.execute(  # noqa: SLF001
            "INSERT INTO shop_orders (customer_id, status, priority, amount) "
            "VALUES (%s, 'pagado', 1, -5)",
            (client.id,),
        )
    session.rollback()


def test_the_migration_rolls_back_cleanly(
    session: SnakeSession, tmp_path: Path
) -> None:
    """Checks the complete REVERSE: what was created is undone and nothing remains."""
    migrations = _migrate(session, tmp_path / "migrations")
    runner = MigrationRunner(session._driver, PostgresDialect())  # noqa: SLF001

    for migration in reversed(migrations):
        runner.rollback(migration)

    remaining = session._driver.fetch_all(  # noqa: SLF001
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE %s",
        ("shop_%",),
    )
    assert remaining == [], "a complete down leaves no orphan tables"


def test_the_second_database_is_just_another_database(tmp_path: Path) -> None:
    """Real multi-connection: ANOTHER database, the SAME container.

    No second server is needed. The named connection resolves its DSN through configuration and
    only sees ITS tables: the autogen of `analytics` does not touch the store ones.
    """
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn_for("analytics"))
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON} (database 'analytics'): {error}")

    try:
        snake_link()
        own = {t.name for t in current_schema(database="analytics")}
        assert "shop_visits" in own
        assert "shop_orders" not in own, "each connection sees ONLY its own tables"

        visits = [snake_table(Visit)]
        driver.execute("DROP TABLE IF EXISTS shop_visits", ())
        for operation in autodetect([], visits):
            for sql in operation.up_sql(PostgresDialect()):
                driver.execute(sql, ())
        driver.commit()

        session = SnakeSession(driver, PostgresDialect())
        session.add(Visit(path="/inicio", duration_ms=120))
        session.commit()
        assert session.count(SnakeQuery(Visit)) == 1
    finally:
        driver.execute("DROP TABLE IF EXISTS shop_visits", ())
        driver.commit()
        driver.close()


def test_the_example_domain_declares_what_it_claims() -> None:
    """Guard on the example itself: if someone removes a piece, the exercise stops exercising."""
    order = snake_table(Order)
    client = snake_table(Customer)

    assert len(order.checks) == 3, (
        "two derived from enums plus the explicit one on amount"
    )
    amount = order.get_column("amount")
    assert amount is not None and (amount.precision, amount.scale) == (12, 2)
    assert any(index.where is not None for index in client.indexes), "the partial index"
    assert snake_table(Visit).database == "analytics"
