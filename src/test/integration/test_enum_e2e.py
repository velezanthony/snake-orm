"""INTEGRATION: an enum goes in as a member and comes out a MEMBER, and filtering by enum finds rows.

The two points where this breaks in silence, and that is why they are here and not in a unit test:

1. THE WAY BACK. If nobody converts, the DB returns the raw `str`/`int` and the attribute stops
   being a member of the enum. It does not fail: the declared type simply stops being the type you
   receive, which is the entire promise of the project.
2. THE FILTER. `filter(Account.status == Status.ACTIVE)` has to send the VALUE as a parameter. If
   the member travels unconverted, the query returns ZERO rows with no error whatsoever, and you
   go mad hunting for the failure somewhere else.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import IntEnum, StrEnum

from snakeorm.core.exceptions import SnakeCheckViolation
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_enum,
    snake_int,
    snake_model,
    snake_table,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


class Level(StrEnum):
    """Nivel de acceso, texto."""

    FREE = "free"
    PRO = "pro"


class Tier(IntEnum):
    """Escalón numérico, ordenable."""

    BRONZE = 1
    GOLD = 3


@snake_model(table="enum_e2e_accounts")
class Account(SnakeModel):
    """Account with one text enum and one numeric enum."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    level: SnakeColumn[Level] = snake_enum(Level, default=Level.FREE)
    tier: SnakeColumn[Tier] = snake_enum(Tier, default=Tier.BRONZE)


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Real session with the table created by the DDL the ORM itself generates."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS enum_e2e_accounts", ())
    driver.execute(emit_create_table(snake_table(Account), PostgresDialect()), ())
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS enum_e2e_accounts", ())
        driver.commit()
        driver.close()


def test_a_member_goes_in_and_a_member_comes_back(session: SnakeSession) -> None:
    """POINT 1: what comes back is the MEMBER of the enum, not the raw str/int."""
    session.add(Account(id=1, level=Level.PRO, tier=Tier.GOLD))
    session.commit()

    found = session.first(SnakeQuery(Account).filter(Account.id == 1))

    assert found is not None
    assert found.level is Level.PRO, (
        "the raw value came back instead of the enum member"
    )
    assert found.tier is Tier.GOLD
    assert isinstance(found.level, Level)


def test_filtering_by_an_enum_member_finds_the_row(session: SnakeSession) -> None:
    """POINT 2: filtering by member finds the row, it does not return zero in silence."""
    session.add(Account(id=1, level=Level.PRO, tier=Tier.GOLD))
    session.add(Account(id=2, level=Level.FREE, tier=Tier.BRONZE))
    session.commit()

    pros = session.all(SnakeQuery(Account).filter(Account.level == Level.PRO))

    assert [account.id for account in pros] == [1], (
        "the filter by enum did not find the row"
    )


def test_filtering_with_in_works_too(session: SnakeSession) -> None:
    """Checks that `in_` with members matches too (the same parameter path)."""
    session.add(Account(id=1, level=Level.PRO, tier=Tier.GOLD))
    session.add(Account(id=2, level=Level.FREE, tier=Tier.BRONZE))
    session.commit()

    rows = session.all(
        SnakeQuery(Account).filter(Account.level.in_([Level.PRO, Level.FREE]))
    )
    assert len(rows) == 2


def test_an_int_enum_keeps_its_order_in_sql(session: SnakeSession) -> None:
    """Checks that an IntEnum compares as a number: `tier > BRONZE` is a real inequality."""
    session.add(Account(id=1, level=Level.PRO, tier=Tier.GOLD))
    session.add(Account(id=2, level=Level.FREE, tier=Tier.BRONZE))
    session.commit()

    rows = session.all(SnakeQuery(Account).filter(Account.tier > Tier.BRONZE))
    assert [account.id for account in rows] == [1]


def test_the_generated_check_rejects_an_invalid_value(session: SnakeSession) -> None:
    """Checks that the CHECK derived from the enum really guards: the DB rejects an outside value.

    The value has to FIT the column for this to measure what it claims. `level` is a `VARCHAR(4)`
    now —the width of `free`, the enum's longest member— so a longer intruder never reaches the
    CHECK; the length refuses it first, and this test would then be passing on the wrong guard.
    `nope` is four characters and is not a member, which is the case the CHECK is the only thing
    standing in the way of.
    """

    with pytest.raises(SnakeCheckViolation, match="CHECK constraint"):
        session._driver.execute(  # noqa: SLF001
            "INSERT INTO enum_e2e_accounts (id, level, tier) VALUES (9, 'nope', 1)",
            (),
        )
    session.rollback()


def test_a_value_too_long_for_the_enum_is_refused_by_the_width(
    session: SnakeSession,
) -> None:
    """And an intruder LONGER than any member dies on the column's width, before the CHECK.

    Deriving the enum's width added a second guard in front of the first, and which one fires
    changes the error the user reads: `hacker` used to come back as a check violation and now comes
    back as a string truncation. Both refuse the write and neither lets the value in, so nothing is
    lost — but a change of message is a change, and in this ORM the message IS the product, so it
    gets asserted instead of being left to be discovered by whoever was reading the old one.
    """
    import psycopg2

    with pytest.raises(psycopg2.errors.StringDataRightTruncation):
        session._driver.execute(  # noqa: SLF001
            "INSERT INTO enum_e2e_accounts (id, level, tier) VALUES (9, 'hacker', 1)",
            (),
        )
    session.rollback()


def test_the_stored_value_is_the_plain_base_type(session: SnakeSession) -> None:
    """Checks that the DB holds an ordinary TEXT ('pro'), not some odd representation of the enum."""
    session.add(Account(id=1, level=Level.PRO, tier=Tier.GOLD))
    session.commit()

    rows = session._driver.fetch_all(  # noqa: SLF001
        "SELECT level, tier FROM enum_e2e_accounts WHERE id = 1", ()
    )
    assert rows[0] == ("pro", 3)
