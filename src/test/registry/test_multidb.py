"""Multi-connection: every model declares WHICH database it lives in.

The EXECUTION seam already existed —`SnakeSession` and `MigrationRunner` take an injected driver—,
so opening two sessions against two DBs already worked. What was missing was everything around it:
knowing which tables go to which DB, and keeping the autogen from creating them ALL in EACH one.

And the guard that really matters: a relation crossing databases does not exist. There is no
possible FK and no possible JOIN, so it is rejected at LINK time —when the application boots— and
not when the `ALTER TABLE` blows up against a table that is not there.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.linker import snake_link
from snakeorm.migration import current_schema
from snakeorm.registry import SnakeRegistry


@snake_model(table="md_users")
class MdUser(SnakeModel):
    """Lives in the default connection."""

    id: SnakeColumn[int] = snake_auto()
    email: SnakeColumn[str] = snake_str()


@snake_model(table="md_events", database="analytics")
class MdEvent(SnakeModel):
    """Lives in another database: the analytics one."""

    id: SnakeColumn[int] = snake_auto()
    label: SnakeColumn[str] = snake_str()


def test_the_default_database_is_named_default() -> None:
    """Checks that a model without `database=` falls into the default connection."""
    assert snake_table(MdUser).database == "default"


def test_a_model_can_declare_its_database() -> None:
    """Checks that the target is READ off the model: declarative and static, with no magic router."""
    assert snake_table(MdEvent).database == "analytics"


def test_current_schema_filters_by_database() -> None:
    """THE REASON the binding exists: without filtering, the autogen would create EVERYTHING in EACH database."""
    default_tables = {table.name for table in current_schema(database="default")}
    analytics_tables = {table.name for table in current_schema(database="analytics")}

    assert "md_users" in default_tables
    assert "md_events" not in default_tables
    # Membership and NOT equality: the registry is global and the whole suite shares it, so other
    # modules may have registered their own models in 'analytics'. What is asserted here is the
    # filtering, not the census.
    assert "md_events" in analytics_tables
    assert "md_users" not in analytics_tables


def test_current_schema_without_a_database_still_returns_everything() -> None:
    """Checks backwards compatibility: without asking for a database, all tables are returned."""
    every = {table.name for table in current_schema()}
    assert {"md_users", "md_events"} <= every


def test_a_relation_across_databases_is_refused_when_linking() -> None:
    """THE GUARD: there is no FK and no JOIN across databases, so it is cut off at link time.

    Without this, the migration would emit an `ALTER TABLE ... REFERENCES` against a table that does
    not exist in that DB, and the failure would arrive at `migrate` —or worse, the query would
    generate an impossible JOIN at runtime—.
    """
    with pytest.raises(SnakeModelDefinitionError, match="crosses databases"):
        snake_link(_CROSS)


def test_a_relation_inside_the_same_database_still_links() -> None:
    """Checks that the guard does not get in the way of the normal case: same DB, relation linked."""
    snake_link(_SAME)  # must not raise

    table = _SAME.table_of(MdCart)
    assert table is not None
    assert [rel.name for rel in table.relationships] == ["owner"]


# The models of the two linking scenarios live at MODULE LEVEL on purpose: the linker resolves the
# annotations with `get_type_hints`, which looks at the module globals. Declared inside a function,
# the target of the relation would not be resolvable.
_CROSS = SnakeRegistry()
_SAME = SnakeRegistry()


@snake_model(table="md_orders", registry=_CROSS)
class MdOrder(SnakeModel):
    """Order in the default DB pointing at a model of ANOTHER database."""

    id: SnakeColumn[int] = snake_auto()
    event_id: SnakeColumn[int] = snake_int()
    event: SnakeToOne[MdRemote] = snake_to_one(event_id)


@snake_model(table="md_remote", database="analytics", registry=_CROSS)
class MdRemote(SnakeModel):
    """The target, which lives in another connection."""

    id: SnakeColumn[int] = snake_auto()


@snake_model(table="md_carts", registry=_SAME)
class MdCart(SnakeModel):
    """Cart and its owner, both in the default connection."""

    id: SnakeColumn[int] = snake_auto()
    owner_id: SnakeColumn[int] = snake_int()
    owner: SnakeToOne[MdOwner] = snake_to_one(owner_id)


@snake_model(table="md_owners", registry=_SAME)
class MdOwner(SnakeModel):
    """Owner of the cart."""

    id: SnakeColumn[int] = snake_auto()


def test_the_renderer_writes_the_database_into_the_migration() -> None:
    """Closes point 2 of the contract: without this, the replay would lose which DB the table belongs to.

    And losing it is not cosmetic: the rebuilt state would stop matching the metadata and the
    autogen would generate the same migration over and over without converging.
    """
    from snakeorm.migration import CreateTable, render_migration

    source = render_migration("0001_analytics", [CreateTable(snake_table(MdEvent))])
    assert 'database="analytics"' in source


def test_a_default_database_is_not_written() -> None:
    """Checks that the default connection does not litter every migration with a redundant field."""
    from snakeorm.migration import CreateTable, render_migration

    source = render_migration("0001_users", [CreateTable(snake_table(MdUser))])
    assert "database=" not in source
