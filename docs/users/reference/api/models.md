# Declaring models

Everything you need to turn a Python class into a table: the decorator that
compiles it, the field specifiers that add SQL information to each column, and the descriptors that
give relationships their typed navigation.

The rule that governs all of it: **the type comes from Python**. A specifier never changes the type
nor contradicts the annotation — it only adds what SQL needs to know.

!!! note "Where this text comes from"

    Everything below the headings is generated from the package's own docstrings, on every build.

## Model and view

A VIEW is a model whose body is a query, so it is rendered in the TARGET dialect — a compound view is written afresh per engine. Where `CREATE OR REPLACE VIEW` is not available the emitter does `DROP` + `CREATE`, which is a declared capability and not a guess.

```python
from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeView,
    snake_int,
    snake_model,
    snake_str,
    snake_view,
)

@snake_model(table="view_sales")
class Sale(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    seller: SnakeColumn[str] = snake_str(max_length=50)
    amount: SnakeColumn[int] = snake_int()

@snake_view(name="active_sellers", query=SnakeQuery(Sale).filter(Sale.amount > 0))
class ActiveSeller(SnakeView):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    seller: SnakeColumn[str] = snake_str(max_length=50)
```

::: snakeorm.model.SnakeModel

::: snakeorm.model.SnakeView
::: snakeorm.decorators.result.SnakeResult

::: snakeorm.decorators.row.SnakeRow

## Decorators

::: snakeorm.decorators.snake_model

::: snakeorm.decorators.snake_view

::: snakeorm.decorators.snake_abstract

::: snakeorm.decorators.snake_db_first

::: snakeorm.decorators.snake_table

::: snakeorm.decorators.snake_result

::: snakeorm.decorators.snake_row

::: snakeorm.decorators.snake_function

::: snakeorm.decorators.snake_trigger

## Descriptors

::: snakeorm.fields.SnakeColumn

::: snakeorm.fields.SnakeToOne

::: snakeorm.fields.SnakeToMany

::: snakeorm.fields.SnakeCollection

## Field specifiers

::: snakeorm.fields.snake_column

::: snakeorm.fields.snake_auto

::: snakeorm.fields.snake_int

::: snakeorm.fields.snake_str

::: snakeorm.fields.snake_float

::: snakeorm.fields.snake_decimal

::: snakeorm.fields.snake_json

::: snakeorm.fields.snake_enum

::: snakeorm.fields.snake_datetime

::: snakeorm.fields.snake_datetimetz

::: snakeorm.fields.snake_time

::: snakeorm.fields.snake_timetz

::: snakeorm.fields.snake_to_one

::: snakeorm.fields.snake_to_many

::: snakeorm.fields.snake_to_many_through

::: snakeorm.fields.snake_discriminator

## Indexes and constraints

::: snakeorm.fields.SnakeIndex

::: snakeorm.metadata.SnakeIndexMethod

::: snakeorm.fields.snake_indexes

::: snakeorm.fields.snake_check

::: snakeorm.fields.snake_checks

## Linking

::: snakeorm.linker.snake_link

::: snakeorm.registry.SnakeRegistry
::: snakeorm.registry.registry

## Declaration enums

::: snakeorm.metadata.SnakeIntSize

::: snakeorm.metadata.SnakeJsonStorage

::: snakeorm.metadata.SnakeEnumStorage

::: snakeorm.metadata.SnakeServerDefault

::: snakeorm.metadata.SnakeFkAction

::: snakeorm.metadata.SnakeIntParams

::: snakeorm.metadata.SnakeStrParams

::: snakeorm.metadata.SnakeDecimalParams

::: snakeorm.metadata.SnakeFloatParams

::: snakeorm.metadata.SnakeJsonParams

::: snakeorm.metadata.SnakeDateTimeParams

::: snakeorm.metadata.SnakeTimeParams

## Compiled metadata

The graph the compiler builds once and every other piece reads. You do not write these by hand, but
they are public because a migration, a check or a trigger you inspect at runtime hands them to you.

::: snakeorm.metadata.SnakeRelationshipKind

::: snakeorm.metadata.SnakeThroughInfo

::: snakeorm.metadata.SnakeCheckInfo

::: snakeorm.metadata.SnakeTriggerInfo

::: snakeorm.metadata.SnakeTriggerEvent

::: snakeorm.metadata.SnakeTriggerTiming
