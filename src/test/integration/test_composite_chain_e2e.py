"""A CHAIN of composite keys, three levels deep, on the three engines.

Composite PK/FK is what this ORM has that the alternatives do not, and it was created on three
engines and checked on one: the DDL half runs everywhere, the BEHAVIOUR half lived in
`test/scenarios/test_composite_keys.py` against a lone Postgres, two levels deep.

This adds the level that was never there — an identifying relationship, where a child's PK is the
parent's composite FK PLUS a new column, twice over:

    ChainProvince (region, code)                                     2 columns
    ChainTown     (province_region, province_code, town_code)        3, the first 2 are the FK
    ChainDistrict (prov_region, prov_code, town_code, district_code) 4, the first 3 are the FK

**The seed is the test.** It is picked so that no single column discriminates a row AND no PROPER
PREFIX of the key does either. The first condition catches a matcher that uses one column instead of
the tuple; the second catches one that uses only the INHERITED part of the key and ignores the
column the level adds — which a naive fixture lets through green, because a parent's key is enough
to tell most rows apart until two children share it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import SnakeColumnNotLoaded, SnakeQuery, SnakeSession
from snakeorm.expressions import count, snake_key, snake_keys
from snakeorm.decorators import snake_model
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
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="cc_provinces")
class ChainProvince(SnakeModel):
    """Level one: a composite PK of two columns.

    Named `Chain*` and not `Province`: `test/scenarios/test_composite_keys.py` already owns those
    names, `snake_link()` links the WHOLE registry, and two models sharing a name made the older
    file's `Town` resolve its relation to THIS `Province` — a `kv_towns JOIN cc_provinces` that only
    appeared when both files ran together.
    """

    region: SnakeColumn[str] = snake_str(primary_key=True, max_length=16)
    code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    towns: SnakeToMany[ChainTown] = snake_to_many("province")


@snake_model(table="cc_towns")
class ChainTown(SnakeModel):
    """Level two: the parent's key IS the first half of this one, plus a column of its own."""

    province_region: SnakeColumn[str] = snake_str(primary_key=True, max_length=16)
    province_code: SnakeColumn[int] = snake_int(primary_key=True)
    town_code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    province: SnakeToOne[ChainProvince] = snake_to_one(province_region, province_code)
    districts: SnakeToMany[ChainDistrict] = snake_to_many("town")


@snake_model(table="cc_districts")
class ChainDistrict(SnakeModel):
    """Level three: a four-column PK whose first three are the FK to a three-column key."""

    prov_region: SnakeColumn[str] = snake_str(primary_key=True, max_length=16)
    prov_code: SnakeColumn[int] = snake_int(primary_key=True)
    town_code: SnakeColumn[int] = snake_int(primary_key=True)
    district_code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    # A column no test needs, so `only()` has something to leave out. Without it the projection
    # would be the whole row and the deferral assertion below would hold vacuously.
    notes: SnakeColumn[str] = snake_str()
    town: SnakeToOne[ChainTown] = snake_to_one(prov_region, prov_code, town_code)


# (region, code, name)
_PROVINCES = [
    ("North", 1, "Northland"),
    ("North", 2, "Highland"),
    ("South", 1, "Southland"),
]

# (province_region, province_code, town_code, name). `North/1/1` and `North/2/1` share `town_code`;
# `North/1/1` and `South/1/1` share both `code` and `town_code`. So neither the new column nor the
# inherited half tells a town apart on its own.
_TOWNS = [
    ("North", 1, 1, "Alpha"),
    ("North", 1, 2, "Beta"),
    ("North", 2, 1, "Gamma"),
    ("South", 1, 1, "Delta"),
]

# (prov_region, prov_code, town_code, district_code, name). `Uno` and `Dos` share the WHOLE
# three-column prefix and differ only in the column this level adds: they are the pair that catches
# a prefix matcher. The rest differ in exactly one column each, and never the same one.
_DISTRICTS = [
    ("North", 1, 1, 1, "Alder"),
    ("North", 1, 1, 2, "Birch"),
    ("North", 1, 2, 1, "Cedar"),
    ("North", 2, 1, 1, "Dogwood"),
    ("South", 1, 1, 1, "Elm"),
]

_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the whole chain seeded. Parents come first: the FKs point upwards."""
    snake_link()
    with three_sessions([ChainProvince, ChainTown, ChainDistrict]) as sessions:
        for session in sessions.values():
            session.add_all(
                [ChainProvince(region=r, code=c, name=n) for r, c, n in _PROVINCES]
            )
            session.commit()
            session.add_all(
                [
                    ChainTown(province_region=r, province_code=c, town_code=t, name=n)
                    for r, c, t, n in _TOWNS
                ]
            )
            session.commit()
            session.add_all(
                [
                    ChainDistrict(
                        prov_region=r,
                        prov_code=c,
                        town_code=t,
                        district_code=d,
                        name=n,
                        notes=f"notes for {n}",
                    )
                    for r, c, t, d, n in _DISTRICTS
                ]
            )
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_deep_path_survives_three_composite_hops(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`ChainDistrict.town.province.name` crosses two composite FKs and lands on the right province.

    Two hops of COMPOSITE key, which is where the descriptor recursion has never been asked to go.
    `Cuatro` is the witness: it shares `town_code` and `district_code` with `Uno` and differs only
    in the province's own code, so a JOIN that dropped a key column would bring it back too.
    """
    session = engines[engine]

    rows = session.all(
        SnakeQuery(ChainDistrict)
        .filter(ChainDistrict.town.province.name == "Northland")
        .order_by(ChainDistrict.district_code.asc(), ChainDistrict.town_code.asc())
    )

    assert sorted(row.name for row in rows) == ["Alder", "Birch", "Cedar"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_include_matches_by_the_whole_key_at_every_level(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Chained `include()` down two levels puts each child under the right parent.

    `Uno` and `Dos` hang off the same town and are the reason this is not vacuous: a prefetch that
    matched on the inherited part of the key alone would still separate every OTHER district
    correctly, and only these two would betray it — by landing under a town that is not theirs.
    """
    session = engines[engine]

    provinces = session.all(
        SnakeQuery(ChainProvince)
        .include(ChainProvince.towns)
        .order_by(ChainProvince.region.asc(), ChainProvince.code.asc())
    )

    assert [(p.region, p.code, len(p.towns)) for p in provinces] == [
        ("North", 1, 2),
        ("North", 2, 1),
        ("South", 1, 1),
    ]

    towns = session.all(
        SnakeQuery(ChainTown)
        .include(ChainTown.districts)
        .order_by(
            ChainTown.province_region.asc(),
            ChainTown.province_code.asc(),
            ChainTown.town_code.asc(),
        )
    )

    assert [
        (
            t.province_region,
            t.province_code,
            t.town_code,
            sorted(d.name for d in t.districts),
        )
        for t in towns
    ] == [
        ("North", 1, 1, ["Alder", "Birch"]),
        ("North", 1, 2, ["Cedar"]),
        ("North", 2, 1, ["Dogwood"]),
        ("South", 1, 1, ["Elm"]),
    ]


@pytest.mark.parametrize("engine", _ENGINES)
def test_any_correlates_on_the_whole_key_down_the_chain(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A nested `.any()` reaches two levels down and correlates on every column of each key."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(ChainProvince)
        .filter(
            ChainProvince.towns.any(
                ChainTown.districts.any(ChainDistrict.name == "Dogwood")
            )
        )
        .order_by(ChainProvince.region.asc(), ChainProvince.code.asc())
    )

    assert [(row.region, row.code) for row in rows] == [("North", 2)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_emitted_join_carries_every_column_of_every_key(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The SQL names all three columns of the second hop's key, not just the first.

    Read alongside the row tests rather than instead of them: the rows prove the answer, the SQL
    proves HOW, and a join missing a column is easier to recognise here than in a wrong result.
    """
    session = engines[engine]
    sql, _ = (
        SnakeQuery(ChainDistrict)
        .filter(ChainDistrict.town.province.name == "Northland")
        .to_sql(session.dialect)
    )

    for column in ("prov_region", "prov_code", "town_code"):
        assert column in sql, f"the join dropped {column} from the composite key"


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_whole_composite_key_selects_exactly_one_row(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Naming every column of a four-column key answers one district and never a neighbour.

    Each of the four columns is shared with some other district, so a filter that dropped any one of
    them would bring back more than one row. That is what makes this an assertion about the KEY and
    not about the data.
    """
    session = engines[engine]

    rows = session.all(
        SnakeQuery(ChainDistrict).filter(
            ChainDistrict.prov_region == "North",
            ChainDistrict.prov_code == 1,
            ChainDistrict.town_code == 1,
            ChainDistrict.district_code == 1,
        )
    )

    assert [row.name for row in rows] == ["Alder"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_ordering_and_distinct_over_a_composite_key(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The key sorts column by column, and `distinct` over part of it collapses what repeats."""
    session = engines[engine]

    ordered = session.all(
        SnakeQuery(ChainDistrict).order_by(
            ChainDistrict.prov_region.asc(),
            ChainDistrict.prov_code.asc(),
            ChainDistrict.town_code.asc(),
            ChainDistrict.district_code.asc(),
        )
    )
    assert [row.name for row in ordered] == [
        "Alder",
        "Birch",
        "Cedar",
        "Dogwood",
        "Elm",
    ]

    towns = session.select(
        SnakeQuery(ChainDistrict)
        .distinct()
        .order_by(ChainDistrict.prov_region.asc(), ChainDistrict.prov_code.asc()),
        ChainDistrict.prov_region,
        ChainDistrict.prov_code,
    )
    assert towns == [("North", 1), ("North", 2), ("South", 1)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_grouping_by_a_composite_key_counts_per_parent(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`GROUP BY` over the three inherited columns gives one row per town, with its own count."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(ChainDistrict)
        .group_by(
            ChainDistrict.prov_region, ChainDistrict.prov_code, ChainDistrict.town_code
        )
        .order_by(
            ChainDistrict.prov_region.asc(),
            ChainDistrict.prov_code.asc(),
            ChainDistrict.town_code.asc(),
        ),
        ChainDistrict.prov_region,
        ChainDistrict.prov_code,
        ChainDistrict.town_code,
        count(ChainDistrict.district_code),
    )

    assert [(r, c, t, int(n)) for r, c, t, n in rows] == [
        ("North", 1, 1, 2),
        ("North", 1, 2, 1),
        ("North", 2, 1, 1),
        ("South", 1, 1, 1),
    ]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_column_at_a_time_asks_a_different_question_from_the_composite_in(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The two ways of filtering by a pair, side by side, on the identifying chain itself.

    `in_()` narrows ONE column, and it is typed for that column's own type: writing
    `ChainProvince.region.in_([("North", 2)])` is refused by both checkers, `tuple[str, int]` where
    `str` was expected. So a caller with a pair in mind used to have one option — one `in_` per
    column — and that is the CARTESIAN PRODUCT.

    Asking for `(North, 2)` and `(South, 1)` shows the difference on this fixture: the product also
    returns `(North, 1)`, which exists in the table and which nobody asked for. `snake_keys` returns
    the two pairs and nothing else.

    THIS TEST USED TO ASSERT THE GAP, and it did it with a pair the two forms happened to agree on
    (`code.in_([1])` has one value, so there was no product to see). It also promised in its NAME
    that a column at a time was all the API offered, which stopped being true the day
    `Cap.ROW_CONSTRUCTOR` got a public reader.
    """
    session = engines[engine]
    wanted = [("North", 2), ("South", 1)]

    composite = session.all(
        SnakeQuery(ChainProvince)
        .filter(
            snake_keys(ChainProvince).in_(
                [
                    snake_key(ChainProvince)
                    .set(ChainProvince.region, region)
                    .set(ChainProvince.code, code)
                    for region, code in wanted
                ]
            )
        )
        .order_by(ChainProvince.region.asc(), ChainProvince.code.asc())
    )
    product = session.all(
        SnakeQuery(ChainProvince)
        .filter(
            ChainProvince.region.in_(["North", "South"]),
            ChainProvince.code.in_([2, 1]),
        )
        .order_by(ChainProvince.region.asc(), ChainProvince.code.asc())
    )

    assert [(row.region, row.code) for row in composite] == wanted
    assert [(row.region, row.code) for row in product] == [
        ("North", 1),
        ("North", 2),
        ("South", 1),
    ], "the column-at-a-time form stopped widening, so this is no longer a comparison"


@pytest.mark.parametrize("engine", _ENGINES)
def test_update_and_delete_aimed_at_a_composite_key_hit_one_row(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A bulk write filtered by the four columns touches one district and reports one.

    Written against its own province so the shared fixture stays usable: the rows are put in and
    taken out inside the test, and what is asserted is the COUNT the write reports plus the state of
    the neighbour that shares three of the four key columns with it.
    """
    session = engines[engine]
    session.add(ChainProvince(region="Temp", code=9, name="Temporary"))
    session.commit()
    session.add(
        ChainTown(province_region="Temp", province_code=9, town_code=1, name="TempTown")
    )
    session.commit()
    session.add_all(
        [
            ChainDistrict(
                prov_region="Temp",
                prov_code=9,
                town_code=1,
                district_code=d,
                name=f"D{d}",
                notes="temp",
            )
            for d in (1, 2)
        ]
    )
    session.commit()

    aimed = SnakeQuery(ChainDistrict).filter(
        ChainDistrict.prov_region == "Temp",
        ChainDistrict.prov_code == 9,
        ChainDistrict.town_code == 1,
        ChainDistrict.district_code == 1,
    )

    changed = session.update_where(aimed, [(ChainDistrict.name, "Renamed")])
    session.commit()
    assert changed == 1

    neighbour = session.first(
        SnakeQuery(ChainDistrict).filter(
            ChainDistrict.prov_region == "Temp", ChainDistrict.district_code == 2
        )
    )
    assert neighbour is not None
    assert neighbour.name == "D2", (
        "the write reached a row that shares three key columns"
    )

    removed = session.delete_where(aimed)
    session.commit()
    assert removed == 1

    session.delete_where(
        SnakeQuery(ChainDistrict).filter(ChainDistrict.prov_region == "Temp")
    )
    session.delete_where(
        SnakeQuery(ChainTown).filter(ChainTown.province_region == "Temp")
    )
    session.delete_where(
        SnakeQuery(ChainProvince).filter(ChainProvince.region == "Temp")
    )
    session.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_upsert_resolves_the_conflict_on_the_whole_composite_key(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The conflict target is every column of the key, and each engine writes that differently.

    Called twice, as elsewhere: the second call is the one that would fail with a duplicate key if
    the ORM had degraded it into a plain INSERT. And a neighbour sharing all but the last column is
    read afterwards — a conflict target that used only part of the key would overwrite THAT instead.
    """
    session = engines[engine]
    session.add(ChainProvince(region="Up", code=1, name="Upsertland"))
    session.commit()
    session.add(
        ChainTown(province_region="Up", province_code=1, town_code=1, name="UpTown")
    )
    session.commit()
    session.add(
        ChainDistrict(
            prov_region="Up",
            prov_code=1,
            town_code=1,
            district_code=2,
            name="Neighbour",
            notes="kept",
        )
    )
    session.commit()

    for label in ("First", "Second"):
        session.upsert(
            ChainDistrict(
                prov_region="Up",
                prov_code=1,
                town_code=1,
                district_code=1,
                name=label,
                notes="upserted",
            ),
            # Inline rather than a named list: the four columns are `SnakeExpr[str]` and
            # `SnakeExpr[int]`, and a variable holding both infers `list[object]`, which the
            # signature rightly refuses. Passed here, it unifies against what `upsert` expects.
            on_conflict=[
                ChainDistrict.prov_region,
                ChainDistrict.prov_code,
                ChainDistrict.town_code,
                ChainDistrict.district_code,
            ],
            update=[ChainDistrict.name],
        )
        session.commit()

    written = session.first(
        SnakeQuery(ChainDistrict).filter(
            ChainDistrict.prov_region == "Up", ChainDistrict.district_code == 1
        )
    )
    neighbour = session.first(
        SnakeQuery(ChainDistrict).filter(
            ChainDistrict.prov_region == "Up", ChainDistrict.district_code == 2
        )
    )

    assert written is not None and written.name == "Second"
    assert neighbour is not None
    assert neighbour.name == "Neighbour", "the conflict target ignored part of the key"

    session.delete_where(
        SnakeQuery(ChainDistrict).filter(ChainDistrict.prov_region == "Up")
    )
    session.delete_where(
        SnakeQuery(ChainTown).filter(ChainTown.province_region == "Up")
    )
    session.delete_where(SnakeQuery(ChainProvince).filter(ChainProvince.region == "Up"))
    session.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_only_and_defer_still_carry_the_whole_key(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A partial row keeps every key column, because without them it cannot be refreshed or written."""
    session = engines[engine]

    partial = session.first(
        SnakeQuery(ChainDistrict)
        .only(ChainDistrict.name)
        .filter(ChainDistrict.prov_region == "South")
    )

    assert partial is not None
    assert partial.name == "Elm"
    assert (
        partial.prov_region,
        partial.prov_code,
        partial.town_code,
        partial.district_code,
    ) == ("South", 1, 1, 1)

    with pytest.raises(SnakeColumnNotLoaded, match="was not loaded"):
        _ = partial.notes
