"""Indexes and constraints CREATED on the three engines, and the ones that cannot say why.

The emitters had tests over the SQL string. A string is the same everywhere; whether an engine
accepts it is not, and an index is the shape where that difference is widest: MySQL has no partial
index at all, and its access methods are not Postgres's.

So the DDL is RUN here, on each engine, and the unique one is checked by writing a DUPLICATE —
created and enforced are not the same thing, and only the second is worth anything.

Partial indexes are NOT covered here, and that is a pointer rather than an omission:
`src/test/migration/test_advanced_indexes.py` holds them, because their two degradations are not
one degradation and deserve their own file. On MySQL a partial SEARCH index WIDENS to the whole
table (same rows, more space) while a partial UNIQUE one is REFUSED — widening that would forbid
duplicates the domain allows.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from snakeorm import SnakeDriver
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.metadata.type_params import SnakeStrParams
from snakeorm.migration import emit_create_index, emit_create_table
from test.scenarios.engines import DIALECTS, three_drivers

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]

_ID = SnakeColumnInfo(name="id", python_type=int)
_EMAIL = SnakeColumnInfo(
    name="email", python_type=str, type_params=SnakeStrParams(max_length=80)
)
_TEAM = SnakeColumnInfo(
    name="team", python_type=str, type_params=SnakeStrParams(max_length=40)
)
_TABLE = SnakeTableInfo(
    name="idx_members",
    columns=(_ID, _EMAIL, _TEAM),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)

_PLAIN = SnakeIndexInfo(columns=("team",), name="ix_members_team")
_UNIQUE = SnakeIndexInfo(columns=("email",), unique=True, name="uq_members_email")
_COMPOSITE = SnakeIndexInfo(columns=("team", "email"), name="ix_members_team_email")


@pytest.fixture
def drivers(tmp_path: pathlib.Path) -> Iterator[dict[str, SnakeDriver]]:
    """A driver per engine with the table created and NO indexes: each test adds its own."""
    with three_drivers([], sqlite_path=str(tmp_path / "idx.db")) as opened:
        for name, driver in opened.items():
            driver.execute(f"DROP TABLE IF EXISTS {_TABLE.name}", ())
            driver.execute(emit_create_table(_TABLE, DIALECTS[name]), ())
            driver.commit()
        try:
            yield opened
        finally:
            for driver in opened.values():
                driver.execute(f"DROP TABLE IF EXISTS {_TABLE.name}", ())
                driver.commit()


@pytest.mark.parametrize("engine", _ENGINES)
@pytest.mark.parametrize(
    "index", [_PLAIN, _UNIQUE, _COMPOSITE], ids=["plain", "unique", "composite"]
)
def test_the_engine_accepts_the_index_the_emitter_wrote(
    index: SnakeIndexInfo, engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """The DDL is RUN. A string test cannot say whether the engine will take it.

    The composite one is here because a multi-column index is where quoting and ordering both show
    up at once, and the three quote identifiers differently.
    """
    driver = drivers[engine]

    driver.execute(emit_create_index(_TABLE, index, DIALECTS[engine]), ())
    driver.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_unique_index_is_enforced_and_not_merely_created(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """Created is not the same as enforced, and only the second one is worth anything.

    A `UNIQUE` the engine accepted and does not police looks identical from the catalogue. What
    tells them apart is a duplicate, so a duplicate is what gets written.
    """
    driver = drivers[engine]
    driver.execute(emit_create_index(_TABLE, _UNIQUE, DIALECTS[engine]), ())
    driver.execute(
        f"INSERT INTO {_TABLE.name} (id, email, team) VALUES (1, 'a@b.c', 'red')", ()
    )
    driver.commit()

    with pytest.raises(Exception):
        driver.execute(
            f"INSERT INTO {_TABLE.name} (id, email, team) VALUES (2, 'a@b.c', 'blue')",
            (),
        )
        driver.commit()
    driver.rollback()


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_index_methods_an_engine_has_are_the_ones_it_declares(engine: str) -> None:
    """`USING <method>` is the engine's vocabulary, and the catalogue is where that is written down.

    Asserted from the catalogue rather than by trying every method against every engine: the set is
    the engine's own and a probe would only rediscover what `Cap.INDEX_METHODS` already states —
    Full on PostgreSQL, Degraded on MySQL (BTREE and HASH, not GIN/GIST/BRIN), Nope on SQLite,
    which has one kind of index and therefore takes no method at all.
    """
    support = DIALECTS[engine].capabilities.support_for(Cap.INDEX_METHODS)

    assert support is not None
    if engine == "postgres":
        assert not isinstance(support, Nope), "PostgreSQL has GIN, GIST and BRIN"
    else:
        assert getattr(support, "reason", "").strip(), (
            f"{engine} does not answer for INDEX_METHODS with a reason"
        )
