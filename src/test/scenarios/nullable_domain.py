"""A domain with a NULLABLE to-one, which no other scenario had.

That absence is why the JOIN planner could emit `INNER` over a relation that may have no partner and
nothing went red for it: `deep_domain` and `composite_domain` declare every to-one as required, so
the wrong join type and the right one return the same rows on every fixture the emitter is tested
against. A defect a test domain CANNOT express is a defect no test can catch.

`Voyage` carries both edges on purpose, so one query exercises the two answers: `port` may be empty
and `berth` may not.
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
from snakeorm.registry import SnakeRegistry

NULLABLE = SnakeRegistry()
"""A registry of its OWN, for the reason `dto/domain.py` writes down beside its own: linking is per
registry, and `snake_link()` over the global one walks every model the whole suite has imported."""


@snake_model(table="harbours", registry=NULLABLE)
class Harbour(SnakeModel):
    """The far end of the NULLABLE edge: a voyage may have no harbour."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    voyages: SnakeToMany[Voyage] = snake_to_many("harbour")


@snake_model(table="berths", registry=NULLABLE)
class Berth(SnakeModel):
    """The far end of the REQUIRED edge, and the control: this one keeps its INNER JOIN."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    code: SnakeColumn[str] = snake_str()


@snake_model(table="voyages", registry=NULLABLE)
class Voyage(SnakeModel):
    """Both edges on one model, so a single query can be asked for the two join types at once."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    code: SnakeColumn[str] = snake_str()
    harbour_id: SnakeColumn[int | None] = snake_int()
    harbour: SnakeToOne[Harbour | None] = snake_to_one(harbour_id)
    berth_id: SnakeColumn[int] = snake_int()
    berth: SnakeToOne[Berth] = snake_to_one(berth_id)
