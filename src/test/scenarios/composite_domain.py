"""A CHAIN of composite primary keys: Canton (2 columns) -> Borough (3) -> Parish (4).

Each level's primary key is the parent's key PLUS one new column, which is the identifying
relationship a weak entity has and the shape no other domain in this suite carries. The existing
composite domain stops at one hop, so nothing here was ever asked of a THIRD level, where a key
stops being a pair and starts being a prefix that can be truncated.

The seed is what makes the tests able to fail, and it is built against TWO different mistakes, not
one:

- **No single column discriminates.** Every value of every key column appears in more than one row,
  so a matcher keyed on one column crosses rows instead of returning nothing, and a wrong answer is
  visible as wrong rows rather than as an empty list.
- **No PROPER PREFIX of a key discriminates either.** This is the one a chain adds. A parish's
  foreign key is `(canton_region, canton_code, borough_code)`; a matcher that used only the
  INHERITED part `(canton_region, canton_code)` would hand every parish of the canton to every
  borough in it. So `(North, 1)` holds two boroughs that each own parishes, and the two sets differ.

Read the other way round: `borough_code = 1` exists under three different cantons, so a matcher
keyed on the NEW column alone crosses cantons. Between the two conditions, only a match on the whole
tuple gives the distribution the tests assert.

Two empties on purpose: `(South, 2)` is a canton with no boroughs, and `(South, 1, 2)` a borough
with no parishes. An empty list is a result, and a chain that breaks at the level below is not.
"""

from __future__ import annotations

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
from snakeorm.model import SnakeModel

_REGION_LENGTH = 16
"""A length on the string key column, because MySQL cannot index a `TEXT` without one.

Left implicit, `snake_str()` maps to `TEXT` and MySQL refuses the `PRIMARY KEY` outright (error
1170), so the table would never exist and the whole file would be about type mapping rather than
about composite keys. The other two engines do not care either way.
"""


@snake_model(table="ck_cantons")
class Canton(SnakeModel):
    """Level one: a composite primary key of two columns and the inverse towards its boroughs."""

    region: SnakeColumn[str] = snake_str(primary_key=True, max_length=_REGION_LENGTH)
    code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=32)
    boroughs: SnakeToMany[Borough] = snake_to_many("canton")


@snake_model(table="ck_boroughs")
class Borough(SnakeModel):
    """Level two: the canton's key plus `borough_code`, so the PK is three columns.

    The first two columns are BOTH the foreign key upwards and part of this row's identity, which is
    what an identifying relationship means and what the ORM has to keep straight in one direction
    without breaking the other.
    """

    canton_region: SnakeColumn[str] = snake_str(
        primary_key=True, max_length=_REGION_LENGTH
    )
    canton_code: SnakeColumn[int] = snake_int(primary_key=True)
    borough_code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=32)
    canton: SnakeToOne[Canton] = snake_to_one(canton_region, canton_code)
    parishes: SnakeToMany[Parish] = snake_to_many("borough")


@snake_model(table="ck_parishes")
class Parish(SnakeModel):
    """Level three: the borough's whole key plus `parish_code`, so the PK is four columns."""

    canton_region: SnakeColumn[str] = snake_str(
        primary_key=True, max_length=_REGION_LENGTH
    )
    canton_code: SnakeColumn[int] = snake_int(primary_key=True)
    borough_code: SnakeColumn[int] = snake_int(primary_key=True)
    parish_code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=32)
    borough: SnakeToOne[Borough] = snake_to_one(
        canton_region, canton_code, borough_code
    )


CANTONS: tuple[tuple[str, int, str], ...] = (
    ("North", 1, "Northland"),
    ("North", 2, "Highland"),
    ("South", 1, "Southland"),
    ("South", 2, "Lowland"),
)
"""A full grid: both regions appear with both codes, so neither column alone names a canton."""

BOROUGHS: tuple[tuple[str, int, int, str], ...] = (
    ("North", 1, 1, "Alpha"),
    ("North", 1, 2, "Beta"),
    ("North", 2, 1, "Gamma"),
    ("South", 1, 1, "Delta"),
    ("South", 1, 2, "Epsilon"),
)
"""`borough_code` 1 and 2 each live under more than one canton, and `(South, 2)` has none at all."""

PARISHES: tuple[tuple[str, int, int, int, str], ...] = (
    ("North", 1, 1, 1, "Ash"),
    ("North", 1, 1, 2, "Birch"),
    ("North", 1, 2, 1, "Cedar"),
    ("North", 2, 1, 1, "Dogwood"),
    ("South", 1, 1, 1, "Elm"),
    ("South", 1, 1, 2, "Fir"),
)
"""Alpha and Beta both own parishes under the SAME canton, which is what catches a truncated key.

`(North, 1)` alone would gather Ash, Birch and Cedar; only the whole `(North, 1, 1)` gives Alpha its
two. And `borough_code = 1` alone would gather five parishes across three cantons.
"""


def cantons() -> list[Canton]:
    """The canton rows as instances, for a session to write."""
    return [Canton(region=r, code=c, name=n) for r, c, n in CANTONS]


def boroughs() -> list[Borough]:
    """The borough rows as instances, for a session to write."""
    return [
        Borough(canton_region=r, canton_code=c, borough_code=b, name=n)
        for r, c, b, n in BOROUGHS
    ]


def parishes() -> list[Parish]:
    """The parish rows as instances, for a session to write."""
    return [
        Parish(
            canton_region=r,
            canton_code=c,
            borough_code=b,
            parish_code=p,
            name=n,
        )
        for r, c, b, p, n in PARISHES
    ]


MODELS: tuple[type[SnakeModel], ...] = (Canton, Borough, Parish)
"""The three levels in creation order, which is also the order a foreign key needs."""
