"""FILTERED prefetch against a real Postgres: `.filter()` narrows the children WITHOUT dropping parents.

`prefetch.filter(cond)` decides WHICH CHILDREN get loaded at that level; a parent with no matching
children gets an EMPTY list but STILL comes along (unlike `query.filter()`, which would discard the
parent). The seed has, on purpose: a parent with children that match AND that do not, a parent with
no matching child at all, and a parent WITHOUT children whatsoever. That way we observe that (a)
each parent loads ONLY the matching ones, (b) all three parents come, and (c) the per-level filter
works in a two-level chain. Its own schema (`pff_*`) so as not to collide with the global registry.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakePrefetch,
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


@snake_model(table="pff_chains")
class PffChain(SnakeModel):
    """Parent: one with mixed children, another with non-matching children, another with none."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    links: SnakeToMany[PffLink] = snake_to_many("chain")


@snake_model(table="pff_links")
class PffLink(SnakeModel):
    """Child: it has a `weight` the prefetch filters on; to-many towards its nodes."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    weight: SnakeColumn[int] = snake_int()
    chain_id: SnakeColumn[int] = snake_int()
    chain: SnakeToOne[PffChain] = snake_to_one(chain_id)
    nodes: SnakeToMany[PffNode] = snake_to_many("link")


@snake_model(table="pff_nodes")
class PffNode(SnakeModel):
    """Grandchild: it has a `year` the second level of the chain filters on."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    year: SnakeColumn[int] = snake_int()
    link_id: SnakeColumn[int] = snake_int()
    link: SnakeToOne[PffLink] = snake_to_one(link_id)


_DDL = (
    "DROP TABLE IF EXISTS pff_nodes, pff_links, pff_chains CASCADE",
    "CREATE TABLE pff_chains (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE pff_links ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL, weight INTEGER NOT NULL,"
    " chain_id INTEGER NOT NULL REFERENCES pff_chains(id))",
    "CREATE TABLE pff_nodes ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL, year INTEGER NOT NULL,"
    " link_id INTEGER NOT NULL REFERENCES pff_links(id))",
)

# Alpha(1): one heavy link (matches >5) and one light one (does not match).
# Beta(2): two links, NONE matches (>5).
# Gamma(3): NO links.
# Alpha's heavy link has an old node (2019, does not match >2020) and a new one (2021, matches).
_SEED = (
    "INSERT INTO pff_chains VALUES (1, 'Alpha'), (2, 'Beta'), (3, 'Gamma')",
    "INSERT INTO pff_links VALUES"
    " (1, 'A-heavy', 10, 1), (2, 'A-light', 2, 1),"
    " (3, 'B-one', 1, 2), (4, 'B-two', 3, 2)",
    "INSERT INTO pff_nodes VALUES (1, 'old', 2019, 1), (2, 'new', 2021, 1)",
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


def test_filter_loads_only_matching_children_and_keeps_every_parent(
    session: SnakeSession,
) -> None:
    """Each parent loads ONLY the matching children; all three parents COME (none is lost).

    Alpha has a heavy link and a light one → only the heavy one. Beta has links but none matches → [].
    Gamma has no links → []. And even so all three parents appear in the result.
    """
    chains = session.all(
        SnakeQuery(PffChain).include(
            SnakePrefetch(PffChain.links).filter(PffLink.weight > 5)
        )
    )
    by_name = {chain.name: chain for chain in chains}

    # (b) all THREE parents come, none is lost to the filter.
    assert sorted(by_name) == ["Alpha", "Beta", "Gamma"]

    # (a) each parent loads ONLY the matching children.
    assert [link.name for link in by_name["Alpha"].links] == ["A-heavy"]
    assert by_name["Beta"].links == []  # it has children, but none matches → empty list
    assert by_name["Gamma"].links == []  # no children whatsoever → empty list


def test_per_level_filter_in_a_two_level_chain(session: SnakeSession) -> None:
    """(c) Per-level filter: of the matching links, only their recent nodes (year > 2020)."""
    chains = session.all(
        SnakeQuery(PffChain).include(
            SnakePrefetch(PffChain.links)
            .filter(PffLink.weight > 5)
            .then(PffLink.nodes)
            .filter(PffNode.year > 2020)
        )
    )
    by_name = {chain.name: chain for chain in chains}

    alpha_links = by_name["Alpha"].links
    assert [link.name for link in alpha_links] == ["A-heavy"]  # only the heavy link
    heavy = alpha_links[0]
    # Of the heavy link, only the new node (2021) matches; the old one (2019) drops out.
    assert [(node.name, node.year) for node in heavy.nodes] == [("new", 2021)]
