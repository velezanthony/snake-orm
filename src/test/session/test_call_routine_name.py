"""The routine NAME of `call(...)` and `execute_procedure(...)`: the one thing that is not a param.

`SELECT * FROM {name}(...)` and `CALL {name}(...)` were the only two places in the ORM where
something handed in from outside reached the SQL string uninspected, in a project whose first
doctrine is that SQL is ALWAYS parametrised. The args already travelled as params; the name could
not, because an engine takes no placeholder where an identifier goes.

So the name is VALIDATED and emitted as written, rather than quoted. Quoting is the cheap move and
it is the wrong one here, and that is measured, not argued: on PostgreSQL a routine created with a
bare `CREATE FUNCTION CalculatePayroll` lands in the catalogue folded to `calculatepayroll`, so
`SELECT * FROM "CalculatePayroll"()` answers `function CalculatePayroll() does not exist`. Quoting
every name would break every mixed-case routine that works today, and break it at the DRIVER — the
worst place, long after the ORM could have said anything useful. The tables and columns the emitter
quotes are a different case: those names come from the metadata graph, and it is the ORM that
created them.

What is checked here: an ordinary name still emits byte for byte what it emitted before, a
schema-qualified name works, an unacceptable one raises `SnakeValueError` naming what arrived, and
both sessions and both doors say the SAME sentence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence

import pytest

from snakeorm.core.exceptions import SnakeValueError
from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.dialects import MySQLDialect, PostgresDialect
from snakeorm.session import AsyncSession, SnakeSession

from test.conftest import NO_SERVER_REASON
from test.scenarios.db import dsn


@snake_row
class _Total(SnakeRow):
    """One scalar column: enough to hydrate whatever the routine gives back."""

    total: int


class _Driver:
    """Fake synchronous driver: it records the SQL and returns nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Sequence[object]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        return []

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append((sql, params))
        return 0

    @property
    def last_insert_id(self) -> int:  # pragma: no cover - never read here
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class _AsyncDriver:
    """The SAME double, awaited: the two sessions have to answer identically."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Sequence[object]]] = []

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        return []

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append((sql, params))
        return 0

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...


def _session() -> tuple[SnakeSession, _Driver]:
    """A synchronous session over the recording double."""
    driver = _Driver()
    return SnakeSession(driver, PostgresDialect()), driver  # type: ignore[arg-type]


# -- What must keep working, byte for byte -------------------------------------------------------

_ACCEPTED = [
    "calculate_payroll",
    "CalculatePayroll",
    "_private_helper",
    "f1",
    "analytics.monthly_sales",
    "snakeorm_db.analytics.monthly_sales",
    "na\u00efve_total",
]


@pytest.mark.parametrize("name", _ACCEPTED)
def test_call_emits_an_acceptable_name_exactly_as_received(name: str) -> None:
    """An acceptable routine name reaches the SQL unchanged: no quoting, no folding, no rewriting.

    Mixed case and the schema qualification are in the list on purpose: those are the two the
    quoting alternative would have silently redirected to a routine that does not exist.
    """
    session, driver = _session()
    session.call(name, [], into=_Total)
    sql, _ = driver.calls[0]
    assert sql == f"SELECT * FROM {name}()"


@pytest.mark.parametrize("name", _ACCEPTED)
def test_execute_procedure_emits_an_acceptable_name_exactly_as_received(
    name: str,
) -> None:
    """The same for the procedure door: it had the SAME hole and gets the SAME answer."""
    session, driver = _session()
    session.execute_procedure(name, [])
    sql, _ = driver.calls[0]
    assert sql == f"CALL {name}()"


def test_a_schema_qualified_name_keeps_its_args_parametrized() -> None:
    """Qualifying by schema changes nothing about the args: they still travel as parameters."""
    session, driver = _session()
    session.call("analytics.sales", ["'; DROP TABLE users; --"], into=_Total)
    sql, params = driver.calls[0]
    assert sql == "SELECT * FROM analytics.sales(%s)"
    assert list(params) == ["'; DROP TABLE users; --"]


# -- What must be refused, and how ---------------------------------------------------------------

_REFUSED = [
    "f(); DROP TABLE users; --",
    "f; DROP TABLE users",
    "my function",
    "1_starts_with_a_digit",
    "",
    "analytics.",
    ".sales",
    "analytics..sales",
    '"CalculatePayroll"',
    "f/*comment*/",
    "sales\nDROP TABLE users",
]


@pytest.mark.parametrize("name", _REFUSED)
def test_call_refuses_a_name_that_is_not_a_plain_identifier(name: str) -> None:
    """An unacceptable name is refused BEFORE any SQL exists, and the complaint quotes what arrived.

    Refusing rather than escaping is the same decision the JSON key path takes: the value cannot be
    a placeholder, so the shape is checked when the statement is BUILT.
    """
    session, driver = _session()
    with pytest.raises(SnakeValueError, match="is not a valid routine name"):
        session.call(name, [], into=_Total)
    assert driver.calls == []


@pytest.mark.parametrize("name", _REFUSED)
def test_execute_procedure_refuses_a_name_that_is_not_a_plain_identifier(
    name: str,
) -> None:
    """The procedure door refuses the same names: one rule, not one rule per door."""
    session, driver = _session()
    with pytest.raises(SnakeValueError, match="is not a valid routine name"):
        session.execute_procedure(name, [])
    assert driver.calls == []


def test_the_complaint_names_what_it_received() -> None:
    """The message quotes the offending name: a rejection that does not say what it rejected is a riddle."""
    session, _ = _session()
    with pytest.raises(SnakeValueError, match=r"'f\(\); DROP TABLE users'"):
        session.call("f(); DROP TABLE users", [], into=_Total)


def test_the_complaint_points_at_the_escape_hatch() -> None:
    """It names `raw(...)`: a name that genuinely needs quotes still has somewhere to go."""
    session, _ = _session()
    with pytest.raises(SnakeValueError, match="raw"):
        session.call("my function", [], into=_Total)


# -- Both sessions, one sentence -----------------------------------------------------------------


def _message_from(action: object, session: object) -> str:
    """The text of the `SnakeValueError` this action raises."""
    with pytest.raises(SnakeValueError) as raised:
        action(session)  # type: ignore[operator]
    return str(raised.value)


def test_both_sessions_refuse_with_the_SAME_message() -> None:
    """Sync and async say it identically, `call` and `execute_procedure` alike.

    Comparing the SQL alone is what let the two halves drift the last time: the same complaint,
    reworded. In an ORM whose doctrine is to shout, the message IS the product.
    """
    bad = "f(); DROP TABLE users"
    sync_session = SnakeSession(_Driver(), PostgresDialect())  # type: ignore[arg-type]
    async_session = AsyncSession(_AsyncDriver(), PostgresDialect())  # type: ignore[arg-type]

    sync_call = _message_from(lambda s: s.call(bad, [], into=_Total), sync_session)
    sync_proc = _message_from(lambda s: s.execute_procedure(bad, []), sync_session)

    with pytest.raises(SnakeValueError) as async_call:
        asyncio.run(async_session.call(bad, [], into=_Total))
    with pytest.raises(SnakeValueError) as async_proc:
        asyncio.run(async_session.execute_procedure(bad, []))

    assert sync_call == sync_proc == str(async_call.value) == str(async_proc.value)


def test_the_rule_does_not_depend_on_the_engine() -> None:
    """MySQL gets the same verdict: the name is an identifier everywhere, not a dialect matter."""
    driver = _Driver()
    session = SnakeSession(driver, MySQLDialect())  # type: ignore[arg-type]
    session.call("analytics.sales", [], into=_Total)
    assert driver.calls[0][0] == "SELECT * FROM analytics.sales()"
    with pytest.raises(SnakeValueError, match="is not a valid routine name"):
        session.call("my function", [], into=_Total)


# -- Against a real PostgreSQL -------------------------------------------------------------------


@pytest.fixture
def real_session() -> Iterator[SnakeSession]:
    """A session against the real PostgreSQL, with a mixed-case routine created UNQUOTED.

    That is the shape a routine takes when a DBA writes `CREATE FUNCTION CalculatePayroll(...)` by
    hand — the overwhelmingly common one — and it is exactly the shape that quoting would break.
    """
    import psycopg2

    from snakeorm.drivers import PsycopgDriver

    try:
        driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute(
        "CREATE OR REPLACE FUNCTION CalculatePayroll(factor int) RETURNS int "
        "AS $$ SELECT factor * 2 $$ LANGUAGE sql",
        (),
    )
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP FUNCTION IF EXISTS CalculatePayroll(int)", ())
        driver.commit()
        driver.close()


@pytest.mark.integration
def test_a_mixed_case_routine_still_resolves_on_a_real_server(
    real_session: SnakeSession,
) -> None:
    """`call('CalculatePayroll', ...)` finds the routine on a real PostgreSQL.

    This is the test that pays for the decision. Quoting the identifier makes this exact call fail
    with `function CalculatePayroll(integer) does not exist`, and the failure arrives from the driver,
    after the round trip, about a routine the user can see with their own eyes in `\\df`.
    """
    [row] = real_session.call("CalculatePayroll", [21], into=_Total)
    assert row.total == 42
