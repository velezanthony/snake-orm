"""`annotate()` returns the scalars with the DECLARED type, against a real Postgres.

Postgres computes `AVG(...)` as `numeric`, and psycopg2 hands a `numeric` over as a `Decimal`.
Without coercion, a result class declaring `avg_power: float` received a `Decimal`: the type
promised by the annotation and the real value did not match. This test exercises it for real.

It is checked with `type(...) is float`, not with `isinstance`: `Decimal` is not a subclass of
`float`, but an equality assert (`Decimal("2.5") == 2.5`) WOULD pass and would prove nothing.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import SnakeResult, snake_model, snake_result
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.linker.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="ac_guilds")
class Guild(SnakeModel):
    """Guild with several members of different power."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    members: SnakeToMany[Member] = snake_to_many("guild")


@snake_model(table="ac_members")
class Member(SnakeModel):
    """Member of a guild, with an integer power."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    power: SnakeColumn[int] = snake_int()
    guild_id: SnakeColumn[int] = snake_int()
    guild: SnakeToOne[Guild] = snake_to_one(guild_id)


@snake_result
class GuildStats(SnakeResult[Guild]):
    """The type of each scalar is declared by the user: that is the source of truth.

    `avg_power` is `float | None` because an `AVG` over zero rows is NULL in SQL. `member_count`
    is not: `COUNT` over zero rows is 0. The Optional is unwrapped at compile time, so the
    coercion to `float` is still applied when the value is not null.
    """

    guild: Guild
    member_count: int
    avg_power: float | None


_DDL = (
    "DROP TABLE IF EXISTS ac_members, ac_guilds CASCADE",
    "CREATE TABLE ac_guilds (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE ac_members ("
    " id INTEGER PRIMARY KEY, power INTEGER NOT NULL,"
    " guild_id INTEGER NOT NULL REFERENCES ac_guilds(id))",
)

# Ferro: powers 1, 2, 4 -> average 2.3333... (numeric, not integer). Yermo: no members.
_SEED = (
    "INSERT INTO ac_guilds VALUES (1, 'Ferro'), (2, 'Yermo')",
    "INSERT INTO ac_members VALUES (1, 1, 1), (2, 2, 1), (3, 4, 1)",
)


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the schema, seeds it and returns a session against the real Postgres."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    snake_link()
    driver = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        driver.execute(statement, ())
    driver.commit()
    return SnakeSession(driver, PostgresDialect())


def test_avg_comes_back_as_the_declared_float(session: SnakeSession) -> None:
    """`AVG` arrives from Postgres as a `Decimal`; the scalar declared `float` must BE a float."""
    rows = session.annotate(
        SnakeQuery(Guild).filter(Guild.name == "Ferro"),
        GuildStats,
        member_count=Guild.members.count(),
        avg_power=Guild.members.avg(Member.power),
    )
    stats = rows[0]
    assert type(stats.avg_power) is float
    assert stats.avg_power == pytest.approx(7 / 3)


def test_count_stays_an_int(session: SnakeSession) -> None:
    """`COUNT` already arrives as an `int` and the coercion does not spoil it (no converter for int)."""
    rows = session.annotate(
        SnakeQuery(Guild).filter(Guild.name == "Ferro"),
        GuildStats,
        member_count=Guild.members.count(),
        avg_power=Guild.members.avg(Member.power),
    )
    assert type(rows[0].member_count) is int
    assert rows[0].member_count == 3


def test_childless_parent_keeps_null_average(session: SnakeSession) -> None:
    """A guild with no members: `COUNT` is 0 but `AVG` is NULL, and the None survives the coercion."""
    rows = session.annotate(
        SnakeQuery(Guild).filter(Guild.name == "Yermo"),
        GuildStats,
        member_count=Guild.members.count(),
        avg_power=Guild.members.avg(Member.power),
    )
    assert rows[0].member_count == 0
    assert rows[0].avg_power is None


def test_base_row_is_hydrated_alongside_the_scalars(session: SnakeSession) -> None:
    """The base row is still a typed model, with its navigation intact."""
    rows = session.annotate(
        SnakeQuery(Guild).filter(Guild.name == "Ferro"),
        GuildStats,
        member_count=Guild.members.count(),
        avg_power=Guild.members.avg(Member.power),
    )
    assert rows[0].guild.name == "Ferro"
    assert type(rows[0].guild.id) is int
