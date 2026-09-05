# Migrations

Migration files are **Python**, not YAML or JSON, and that is not a stylistic
choice: `python_type` is a Python type, and serialising it to JSON would need a name-to-type registry
— a second, worse type system. In `.py` it is an import and a reference.

Each operation knows how to apply itself and how to undo itself. What an engine cannot do is stopped
in the PLAN, with a readable reason, rather than halfway through a deploy.

!!! note "Where this text comes from"

    Everything below the headings is generated from the package's own docstrings, on every build.

    The headings themselves are written by hand, so this page can fall behind the module — it had,
    by seven operations. The list that cannot fall behind is the module's own:

    ```bash
    rg -n '^class ' src/snakeorm/migration/operations.py
    ```

## Runners

A migration declares what it comes AFTER, and the loader turns those declarations into one order across packages. A cycle is refused out loud, naming the migrations that close it — picking an order and hoping is the one thing it will not do.

```python
from snakeorm.migration import Migration

class AddOrderTotals(Migration):
    """A migration from another package can be named as a dependency."""

    depends_on = ["billing.0003_add_plans"]
    operations = [...]
```

::: snakeorm.migration.Migration

::: snakeorm.migration.MigrationRunner

::: snakeorm.migration.AsyncMigrationRunner

## Autodetection

::: snakeorm.migration.autodetect

::: snakeorm.migration.replay

::: snakeorm.migration.diff_schema

::: snakeorm.migration.render_migration

::: snakeorm.migration.load

::: snakeorm.migration.drop_order

## Schemas

::: snakeorm.migration.CreateSchema

::: snakeorm.migration.DropSchema

## Table operations

::: snakeorm.migration.CreateTable

::: snakeorm.migration.DropTable

::: snakeorm.migration.RenameTable

::: snakeorm.migration.RebuildTable

::: snakeorm.migration.AlterTableComment

::: snakeorm.migration.AddColumn

::: snakeorm.migration.DropColumn

::: snakeorm.migration.RenameColumn

::: snakeorm.migration.AlterColumn

`RebuildTable` takes a table from one CONSTRAINT shape to another, and that is SQLite's way out: it
has no `ALTER TABLE ADD/DROP CONSTRAINT` and never will, so a CHECK or a foreign key on a table that
ALREADY EXISTS can only get there by remaking the table around it — create the new one, copy the
rows, drop the old one, rename. The operation names no engine: Postgres and MySQL get the single
minimal `ALTER TABLE ... ADD CONSTRAINT`, SQLite gets the whole rebuild.

It takes two WHOLE `SnakeTableInfo` snapshots, plus the triggers hanging off the table — the rebuild
drops them along with it and owes them back. And it REFUSES a pair that disagrees about anything but
CHECKs and foreign keys, naming what disagrees: a difference in columns would apply on SQLite (which
recreates the table from `after`) and not on Postgres (whose minimal `ALTER` emits nothing for it),
leaving the two engines holding different schemas with neither saying a word. Columns keep their own
operations, and dropping one a foreign key still holds is NOT this operation: SQLite has no
`DROP CONSTRAINT` to take the key out of the way first either, so that one is a hand-written
`RunSQL`, which is the user's call — see [known limits](../limits.md).

```python
from dataclasses import replace

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)
from snakeorm.migration import RebuildTable

tag_id = SnakeColumnInfo(name="id", python_type=int, attr_name="id", autoincrement=True)
parent_id = SnakeColumnInfo(
    name="parent_id", python_type=int, nullable=True, attr_name="parent_id"
)

# The WHOLE table as this migration finds it: on SQLite the rebuild recreates it from `after`, so
# anything left out of the snapshot is structure lost without a word.
tags = SnakeTableInfo(
    name="tags",
    columns=(tag_id, parent_id),
    primary_key=SnakePrimaryKeyInfo(columns=(tag_id,)),
)
parent = SnakeRelationshipInfo(
    name="parent",
    target="Tag",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="Tag", pairs=(("parent_id", "id"),)),
    target_table="public.tags",
)

operations = [
    RebuildTable(
        before=tags,
        after=replace(tags, relationships=(parent,)),
        triggers=(),
    ),
]
```

## Constraints and indexes

::: snakeorm.migration.CreateIndex

::: snakeorm.migration.DropIndex

::: snakeorm.migration.AddCheck

::: snakeorm.migration.DropCheck

::: snakeorm.migration.AddForeignKey

::: snakeorm.migration.DropForeignKey

## Views, functions and triggers

::: snakeorm.migration.CreateView

::: snakeorm.migration.DropView

::: snakeorm.migration.AlterView

::: snakeorm.migration.CreateFunction

::: snakeorm.migration.DropFunction

::: snakeorm.migration.AlterFunction

::: snakeorm.migration.CreateTrigger

::: snakeorm.migration.DropTrigger

::: snakeorm.migration.AlterTrigger

## Escape hatches

::: snakeorm.migration.RunSQL

::: snakeorm.migration.RunPython

