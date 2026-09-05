"""INTEGRATION: DB-first scaffolding against a REAL database.

It is the whole cycle: a schema is created by hand (like the one you find in a legacy project), it
is introspected, the models are generated, the generated file is EXECUTED and it is checked that
the resulting models are usable and that migrations IGNORE them.

Introspection can only be tested against a real engine: reading `pg_catalog` with a double would be
testing the double.

It skips gracefully if there is no Postgres.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import PsycopgDriver
from snakeorm.introspection import PostgresIntrospector, render_models
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_LEGACY_SCHEMA = [
    "DROP TABLE IF EXISTS sc_orders, sc_clients, sc_audit CASCADE",
    """CREATE TABLE sc_clients (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        nickname TEXT,
        balance NUMERIC NOT NULL
    )""",
    """CREATE TABLE sc_orders (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES sc_clients(id),
        placed_at TIMESTAMPTZ NOT NULL
    )""",
    "CREATE INDEX ix_sc_orders_placed ON sc_orders (placed_at)",
    "COMMENT ON TABLE sc_clients IS 'Customers heredados'",
    "COMMENT ON COLUMN sc_clients.email IS 'Correo de acceso'",
    # WITHOUT a primary key, on purpose: a log table is the most common case of a legacy schema,
    # and it was precisely the one that generated a file impossible to import.
    "CREATE TABLE sc_audit (occurred_at TIMESTAMPTZ NOT NULL, detail TEXT NOT NULL)",
]


@pytest.fixture
def driver() -> Iterator[PsycopgDriver]:
    """Real driver with a LEGACY schema created by hand, without going through the ORM."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    for statement in _LEGACY_SCHEMA:
        connection.execute(statement, ())
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute(
            "DROP TABLE IF EXISTS sc_orders, sc_clients, sc_audit CASCADE", ()
        )
        connection.commit()
        connection.close()


def test_it_reads_the_tables_columns_and_types(driver: PsycopgDriver) -> None:
    """Checks that introspection rebuilds the graph with Python types, not SQL strings."""
    tables = {table.name: table for table in PostgresIntrospector(driver).tables()}

    assert {"sc_clients", "sc_orders"} <= set(tables)
    clients = tables["sc_clients"]
    types = {column.name: column.python_type for column in clients.columns}
    assert types["email"] is str
    assert types["id"] is int
    from decimal import Decimal

    assert types["balance"] is Decimal


def test_it_reads_nullability_uniqueness_and_the_primary_key(
    driver: PsycopgDriver,
) -> None:
    """Checks the details that make the model usable, not just the list of columns."""
    tables = {table.name: table for table in PostgresIntrospector(driver).tables()}
    clients = tables["sc_clients"]

    by_name = {column.name: column for column in clients.columns}
    assert by_name["nickname"].nullable is True
    assert by_name["email"].nullable is False
    assert by_name["email"].unique is True
    assert by_name["id"].autoincrement is True, (
        "a SERIAL is recognised by its nextval() default"
    )
    assert [column.name for column in clients.primary_key.columns] == ["id"]


def test_it_reads_indexes_comments_and_foreign_keys(driver: PsycopgDriver) -> None:
    """Checks that indexes, comments and FKs come back too."""
    tables = {table.name: table for table in PostgresIntrospector(driver).tables()}

    assert tables["sc_clients"].db_comment == "Customers heredados"
    email = tables["sc_clients"].get_column("email")
    assert email is not None and email.db_comment == "Correo de acceso"
    assert [index.name for index in tables["sc_orders"].indexes] == [
        "ix_sc_orders_placed"
    ]
    assert [rel.target for rel in tables["sc_orders"].relationships] == ["sc_clients"]


def test_the_generated_file_is_valid_python_that_declares_models(
    driver: PsycopgDriver, tmp_path: Path
) -> None:
    """THE COMPLETE CYCLE: the file is generated, it is EXECUTED, and the models exist and are usable.

    The class is `PublicScClients`, and both halves of that name are decisions.

    `Clients` and not `Client`: CapWords is mechanical and stays, while removing a trailing `s` is a
    guess about ENGLISH — it turned `status` into `Statu` and `direcciones` into `Direccione`, and
    was right in Spanish only by accident.

    `Public` and not nothing: the schema is read even when it is `public`, because `sales.orders`
    beside `hr.orders` is ordinary and without the prefix they are ONE class — the mirror keeps
    whichever came last and says nothing. Prefixing only for non-`public` would be a rule with a
    special case in it. `--no-schema-prefix` turns it off and the collisions get reported instead.

    The mirror stays reversible through `table="sc_clients"` on the line above either way.
    """
    introspector = PostgresIntrospector(driver)
    source = _scoped(render_models(introspector.tables(), introspector.unsupported()))

    module = _import_generated(source, tmp_path / "models_generated.py")

    client_model = module.PublicScClients
    assert isinstance(client_model, type)
    assert "DO NOT EDIT BY HAND" in source
    assert 'table="sc_clients"' in source, (
        "the SQL name is never guessed: it goes explicit"
    )


def test_the_generated_models_are_ignored_by_migrations(
    driver: PsycopgDriver, tmp_path: Path
) -> None:
    """THE KEY TO THE DESIGN: a mirror does not enter the autogen, so there is no baseline to fake."""
    from snakeorm.migration import current_schema

    introspector = PostgresIntrospector(driver)
    source = _scoped(render_models(introspector.tables(), introspector.unsupported()))

    module = _import_generated(source, tmp_path / "scoped_models.py")

    assert module.scoped.models(), (
        "the mirrors ARE registered: they are queried normally"
    )
    assert current_schema(module.scoped) == [], (
        "but the autogen does NOT see them: it does not govern them"
    )


def test_unsupported_objects_are_reported_not_dropped(driver: PsycopgDriver) -> None:
    """Checks that whatever the ORM does not represent COMES OUT somewhere, instead of vanishing.

    A trigger is still there and still acting even if the model never mentions it. Keeping quiet
    about it would make people believe the mirror covers the entire database.
    """
    driver.execute(
        "CREATE OR REPLACE FUNCTION sc_noop() RETURNS trigger AS "
        "$$ BEGIN RETURN NEW; END; $$ LANGUAGE plpgsql",
        (),
    )
    driver.execute(
        "CREATE TRIGGER sc_touch BEFORE INSERT ON sc_clients "
        "FOR EACH ROW EXECUTE FUNCTION sc_noop()",
        (),
    )
    driver.commit()

    warnings = PostgresIntrospector(driver).unsupported()
    assert any("sc_touch" in item for item in warnings)

    source = render_models(PostgresIntrospector(driver).tables(), warnings)
    assert "INTROSPECTION WARNINGS" in source
    assert "sc_touch" in source


def _import_generated(source: str, path: Path) -> ModuleType:
    """Writes the generated file and IMPORTS it for real, which is what a user does.

    An `exec` into a loose dictionary will not do: the compiler resolves the annotations against
    the model's MODULE GLOBALS, and an anonymous namespace is not a module. Importing it for real
    also proves what really matters: that the generated file WORKS as a file.
    """
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = (
        module  # the compiler looks it up by `__module__` for the annotations
    )
    spec.loader.exec_module(module)
    return module


def _scoped(source: str) -> str:
    """Rewrites the generated file so that it registers into an ISOLATED registry.

    The global registry has a guard against two models mapping to the same table, and rightly so:
    it is what catches a `table=` duplicated by copy and paste. Here the same mirror would be
    imported twice in the same test session, so each one goes to its own registry instead of
    loosening the guard.
    """
    # It anchors on `from __future__ import annotations` (ALWAYS present) and not on the snakeorm
    # import line, which is now dynamic: the renderer adds SnakeIntSize/SnakeJsonStorage when a
    # column uses them, so its exact text is no longer fixed.
    return source.replace(
        "from __future__ import annotations",
        "from __future__ import annotations\n"
        "from snakeorm.registry import SnakeRegistry\n"
        "scoped = SnakeRegistry()",
    ).replace("@snake_db_first(", "@snake_db_first(registry=scoped, ")


def test_a_table_without_a_primary_key_scaffolds_and_imports(
    driver: PsycopgDriver, tmp_path: Path
) -> None:
    """A legacy table WITHOUT a PK produces a mirror that IMPORTS and can be queried.

    It is the canonical DB-first use case —logs, staging, imports, join tables— and the scaffolding
    wrote it without a care, exited with 0, and the file blew up on import with "debe declarar al
    menos una PK". The command claimed success and delivered something useless.

    The PK is demanded of what WE GOVERN. A mirror's schema belongs to the sysadmin: if their table
    has no PK, it has none, and it is not our place to invent one.
    """
    tables = [t for t in PostgresIntrospector(driver).tables() if t.name == "sc_audit"]
    module = _import_generated(
        _scoped(render_models(tables)), tmp_path / "mirror_sin_pk.py"
    )

    model = module.PublicScAudit
    table = module.scoped.table_of(model)
    assert table is not None
    assert table.primary_key.columns == (), (
        "the table has no PK and the mirror must not invent one either"
    )
    assert [column.name for column in table.columns] == ["occurred_at", "detail"]
