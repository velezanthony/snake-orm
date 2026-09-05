"""The multi-tenancy predicate EXECUTED on the three engines: whose organisation owns each contract.

`Contract.owner.memberships.any(...)` is a correlated EXISTS hanging off a JOINed alias, and the
alias is written by the ORM. The emitted shape is asserted next door in `src/test/sql`; what only
the engines can say is that it parses and picks the rows the domain means.

The seed makes a wrong correlation visible in the ROWS as well: Ada (user 1) belongs to Acme and to
Globex, Linus (2) only to Globex, Grace (3) to nothing, and every contract id is in the thousands.
Correlating against the CONTRACT instead of against its owner compares a membership's `user_id`
against those, and hands back nothing at all.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import SnakeQuery, SnakeSession
from snakeorm.linker import snake_link
from test.scenarios.engines import three_sessions
from test.scenarios.tenancy_domain import MODELS, Contract, Membership, seed

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines carrying the same tenancy graph."""
    snake_link()
    with three_sessions(list(MODELS)) as sessions:
        for session in sessions.values():
            seed(session._driver)
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_contracts_are_reached_through_their_owners_memberships(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Globex holds Ada's and Linus's contracts; Grace's is out because she is in no organisation."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Contract)
        .filter(Contract.owner.memberships.any(Membership.organization_id == 20))
        .order_by(Contract.id.asc())
    )

    assert [row.alias for row in rows] == ["ada-1", "linus-1"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_other_organisation_picks_a_different_set(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Acme holds only Ada's, so the predicate is answering about the organisation and not the JOIN."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Contract)
        .filter(Contract.owner.memberships.any(Membership.organization_id == 10))
        .order_by(Contract.id.asc())
    )

    assert [row.alias for row in rows] == ["ada-1"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_count_through_the_to_one_reports_zero_and_not_a_missing_row(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Grace has no memberships, so her contract must come back with 0 rather than disappear.

    A correlated aggregate does not restrict the outer row, and the JOIN in front of it must not
    either — that is the vector a row count would otherwise miss entirely.
    """
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Contract).order_by(Contract.id.asc()),
        Contract.alias,
        Contract.owner.memberships.count(),
    )

    assert rows == [("ada-1", 2), ("linus-1", 1), ("grace-1", 0)]
