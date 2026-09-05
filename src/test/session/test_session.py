"""Tests for SnakeSession: it runs a COLORLESS query through the driver and maps rows to models.

The session is the only thing with "color" (it executes). It is tested with a FAKE driver that
returns predefined rows: NO Postgres needed. This is where the generic T comes back to life
(list[T]).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from uuid import UUID

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeEmitError, SnakeUnsupportedFeature
from snakeorm.fields import SnakeColumn, snake_column, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_model
class _User(SnakeModel):
    """Test model (no name override: SQL name == attribute)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    username: SnakeColumn[str] = snake_str()


@snake_model
class _Person(SnakeModel):
    """Model with a name override: the `age` attribute maps to the SQL column `age`."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    age: SnakeColumn[int] = snake_int(name="age")


@snake_model
class _Doc:
    """Model with a UUID column, to test type coercion in `select()`."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    code: SnakeColumn[UUID] = snake_column()


class _SmallNoReturningDialect(PostgresDialect):
    """Postgres with a tiny parameter ceiling and no RETURNING, to watch the chunking."""

    supports_returning = False
    max_bind_params = 4  # with 2 columns per row → batches of 2 rows


class _NoUpsertDialect(PostgresDialect):
    """Postgres, but declaring that it does NOT support upsert, to test the rejection."""

    supports_upsert = False


class _FakeDriver:
    """Fake driver: returns predefined rows and records the SQL/commits executed (no DB)."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[str, Sequence[object]]] = []
        self.committed = 0
        self.rolled_back = 0

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        return self.rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the
        framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append((sql, params))
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover
        ...


def test_all_maps_rows_to_model_instances() -> None:
    """Verifies that .all() returns model instances holding the values of each row."""
    driver = _FakeDriver(rows=[(1, "Ana"), (2, "Bob")])
    session = SnakeSession(driver, PostgresDialect())
    users = session.all(SnakeQuery(_User))
    assert isinstance(users[0], _User)
    assert [(u.id, u.username) for u in users] == [(1, "Ana"), (2, "Bob")]


def test_all_sends_compiled_sql_to_driver() -> None:
    """Verifies that the session compiles the query and passes (sql, params) to the driver."""
    driver = _FakeDriver(rows=[])
    session = SnakeSession(driver, PostgresDialect())
    session.all(SnakeQuery(_User).filter(_User.id > 5))
    sql, params = driver.calls[0]
    assert sql.endswith('WHERE "id" > %s')
    assert params == (5,)


def test_all_empty_result_is_empty_list() -> None:
    """Verifies that with no rows it returns an empty list."""
    session = SnakeSession(_FakeDriver(rows=[]), PostgresDialect())
    assert session.all(SnakeQuery(_User)) == []


def test_all_maps_name_overridden_column_to_python_attr() -> None:
    """Verifies the return trip with an override: the SQL column `age` maps to the `age` attribute."""
    driver = _FakeDriver(rows=[(1, 30)])
    session = SnakeSession(driver, PostgresDialect())
    people = session.all(SnakeQuery(_Person))
    assert people[0].age == 30


def test_first_returns_first_model() -> None:
    """Verifies that .first() returns the first row as an instance of the model."""
    driver = _FakeDriver(rows=[(1, "Ana")])
    session = SnakeSession(driver, PostgresDialect())
    user = session.first(SnakeQuery(_User))
    assert user is not None
    assert (user.id, user.username) == (1, "Ana")


def test_first_returns_none_when_empty() -> None:
    """Verifies that .first() returns None when there are no rows."""
    session = SnakeSession(_FakeDriver(rows=[]), PostgresDialect())
    assert session.first(SnakeQuery(_User)) is None


def test_first_applies_limit_1() -> None:
    """Verifies that .first() compiles with LIMIT 1 (it does not pull the whole table)."""
    driver = _FakeDriver(rows=[(1, "Ana")])
    session = SnakeSession(driver, PostgresDialect())
    session.first(SnakeQuery(_User))
    sql, params = driver.calls[0]
    assert sql.endswith("LIMIT %s")
    assert params == (1,)


def test_add_sends_insert_with_instance_values() -> None:
    """Verifies that .add() emits an INSERT with the values of the instance."""
    driver = _FakeDriver(
        rows=[(1, "Ana")]
    )  # wide RETURNING: the row brings back every column
    session = SnakeSession(driver, PostgresDialect())
    session.add(_User(id=1, username="Ana"))
    sql, params = driver.calls[0]
    assert sql.startswith('INSERT INTO "public"."_users"')
    assert params == (1, "Ana")


def test_add_sets_returned_pk_back_on_instance() -> None:
    """Verifies that the RETURNING of the PK is assigned back onto the instance."""
    driver = _FakeDriver(rows=[(99, "Ana")])  # the DB returns a different id
    session = SnakeSession(driver, PostgresDialect())
    user = _User(id=1, username="Ana")
    session.add(user)
    assert user.id == 99


def test_add_sets_all_returned_columns_back_on_instance() -> None:
    """Verifies that the wide RETURNING reassigns EVERY column, not just the PK.

    A value set by the server (simulated here: the DB returns a different username) comes back to
    the object.
    """
    driver = _FakeDriver(rows=[(99, "server-side")])
    session = SnakeSession(driver, PostgresDialect())
    user = _User(id=1, username="Ana")
    session.add(user)
    assert (user.id, user.username) == (99, "server-side")


def test_add_returns_the_instance() -> None:
    """Verifies that .add() returns the same instance (so it can be chained)."""
    session = SnakeSession(_FakeDriver(rows=[(1, "Ana")]), PostgresDialect())
    user = _User(id=1, username="Ana")
    assert session.add(user) is user


def test_commit_and_rollback_delegate_to_driver() -> None:
    """Verifies that the session's commit/rollback delegate to the driver."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.commit()
    session.rollback()
    assert (driver.committed, driver.rolled_back) == (1, 1)


def test_context_manager_commits_on_clean_exit() -> None:
    """Verifies that leaving the `with` without an error commits automatically."""
    driver = _FakeDriver(rows=[(1, "Ana")])
    with SnakeSession(driver, PostgresDialect()) as session:
        session.add(_User(id=1, username="Ana"))
    assert (driver.committed, driver.rolled_back) == (1, 0)


def test_context_manager_rolls_back_and_reraises_on_exception() -> None:
    """Verifies that an exception inside the `with` causes a rollback and gets propagated."""
    driver = _FakeDriver()
    with pytest.raises(ValueError, match="boom"):
        with SnakeSession(driver, PostgresDialect()) as session:
            session.delete(_User(id=1, username="Ana"))
            raise ValueError("boom")
    assert (driver.committed, driver.rolled_back) == (0, 1)


def test_context_manager_yields_the_session() -> None:
    """Verifies that the `with` hands over the session itself."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with session as entered:
        assert entered is session


def test_delete_emits_delete_by_pk() -> None:
    """Verifies that .delete() emits a DELETE filtered by the primary key."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.delete(_User(id=5, username="Ana"))
    sql, params = driver.calls[0]
    assert sql == 'DELETE FROM "public"."_users" WHERE "id" = %s'
    assert params == (5,)


def test_count_returns_scalar() -> None:
    """Verifies that .count() compiles COUNT(*) and returns the scalar from the driver."""
    driver = _FakeDriver(rows=[(7,)])
    session = SnakeSession(driver, PostgresDialect())
    assert session.count(SnakeQuery(_User).filter(_User.id > 0)) == 7
    sql, _ = driver.calls[0]
    assert sql.startswith("SELECT COUNT(*) FROM")


def test_exists_returns_bool() -> None:
    """Verifies that .exists() compiles EXISTS and returns the boolean from the driver."""
    driver = _FakeDriver(rows=[(True,)])
    session = SnakeSession(driver, PostgresDialect())
    assert session.exists(SnakeQuery(_User).filter(_User.id == 1)) is True
    sql, _ = driver.calls[0]
    assert sql.startswith("SELECT EXISTS(")


def test_update_emits_update_of_non_pk_columns_by_pk() -> None:
    """Verifies that .update() emits an UPDATE of the non-PK columns filtered by the PK."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.update(_User(id=1, username="Bob"))
    sql, params = driver.calls[0]
    assert sql == 'UPDATE "public"."_users" SET "username" = %s WHERE "id" = %s'
    assert params == ("Bob", 1)


def test_add_all_fills_returned_columns_in_order() -> None:
    """Verifies that .add_all() reassigns the returned columns to each instance, IN ORDER."""
    driver = _FakeDriver(rows=[(10, "Ana"), (20, "Bob")])
    session = SnakeSession(driver, PostgresDialect())
    ana, bob = _User(id=1, username="Ana"), _User(id=2, username="Bob")
    session.add_all([ana, bob])
    assert (ana.id, bob.id) == (10, 20)


def test_add_all_emits_a_single_multirow_insert() -> None:
    """Verifies that a batch that fits whole goes in ONE single statement with several VALUES."""
    driver = _FakeDriver(rows=[(1, "Ana"), (2, "Bob")])
    session = SnakeSession(driver, PostgresDialect())
    session.add_all([_User(id=1, username="Ana"), _User(id=2, username="Bob")])
    assert len(driver.calls) == 1
    sql, params = driver.calls[0]
    assert "VALUES (%s, %s), (%s, %s)" in sql
    assert params == (1, "Ana", 2, "Bob")


def test_add_all_chunks_by_max_bind_params() -> None:
    """Verifies the chunking: with max_bind_params=4 and 2 columns/row, 5 rows → 3 statements (2,2,1)."""
    driver = _FakeDriver()
    session = SnakeSession(driver, _SmallNoReturningDialect())
    session.add_all([_User(id=i, username=f"u{i}") for i in range(5)])
    assert len(driver.calls) == 3
    tuple_counts = [sql.count("(%s, %s)") for sql, _ in driver.calls]
    assert tuple_counts == [2, 2, 1]


def test_add_all_empty_is_a_noop() -> None:
    """Verifies that .add_all([]) emits no statement at all."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.add_all([])
    assert driver.calls == []


def test_add_all_rejects_mixed_models() -> None:
    """Verifies that mixing models in the same batch raises SnakeEmitError."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(SnakeEmitError, match="every instance to be of the same model"):
        session.add_all([_User(id=1, username="Ana"), _Person(id=2, age=30)])


def test_upsert_emits_on_conflict_do_update() -> None:
    """Verifies that .upsert(update=...) emits an INSERT with `ON CONFLICT ... DO UPDATE SET`."""
    driver = _FakeDriver(rows=[(1, "Ana")])
    session = SnakeSession(driver, PostgresDialect())
    session.upsert(
        _User(id=1, username="Ana"), on_conflict=[_User.id], update=[_User.username]
    )
    sql, _ = driver.calls[0]
    assert 'ON CONFLICT ("id") DO UPDATE SET "username" = EXCLUDED."username"' in sql


def test_upsert_do_nothing_without_update() -> None:
    """Verifies that .upsert() without `update` emits `ON CONFLICT ... DO NOTHING`."""
    driver = _FakeDriver(rows=[])  # DO NOTHING on conflict returns no row
    session = SnakeSession(driver, PostgresDialect())
    session.upsert(_User(id=1, username="Ana"), on_conflict=[_User.id])
    sql, _ = driver.calls[0]
    assert 'ON CONFLICT ("id") DO NOTHING' in sql


def test_upsert_unsupported_dialect_raises() -> None:
    """Verifies that a dialect without upsert raises SnakeUnsupportedFeature (it is not emulated with a SELECT)."""
    session = SnakeSession(_FakeDriver(), _NoUpsertDialect())
    with pytest.raises(SnakeUnsupportedFeature, match="emulation has a race condition"):
        session.upsert(_User(id=1, username="Ana"), on_conflict=[_User.id])


def test_upsert_empty_on_conflict_raises() -> None:
    """Verifies that an upsert with no conflict columns raises SnakeEmitError."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(SnakeEmitError, match="needs at least one conflict column"):
        session.upsert(_User(id=1, username="Ana"), on_conflict=[])


def test_select_coerces_projected_uuid_column() -> None:
    """Verifies that a projected UUID column is coerced to uuid.UUID (psycopg2 hands it over as str)."""
    raw = "12345678-1234-5678-1234-567812345678"
    driver = _FakeDriver(rows=[(raw,)])
    session = SnakeSession(driver, PostgresDialect())
    result = session.select(SnakeQuery(_Doc), _Doc.code)
    assert result == [(UUID(raw),)]
    assert isinstance(result[0][0], UUID)
