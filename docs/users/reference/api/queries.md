# Building queries

A query is a **value**: it does not execute, it has no connection, and every
method returns a new one. That is what lets the same query be run by the synchronous session or the
asynchronous one without knowing which — and what makes stacking fragments work without any extra
machinery.

Comparing a column does not give you a `bool`. `User.age > 18` is a `SnakeCondition`, and that is
the whole trick behind typed deep navigation.

!!! note "Where this text comes from"

    Everything below the headings is generated from the package's own docstrings, on every build.

## Queries

::: snakeorm.query.SnakeQuery

::: snakeorm.query.SnakeJoinedQuery

::: snakeorm.query.SnakeJoin

::: snakeorm.query.SnakeCompound

::: snakeorm.query.SnakeSetOp

::: snakeorm.query.SnakeRecursive

## Expressions

::: snakeorm.expressions.SnakeExpr

::: snakeorm.expressions.SnakeCondition

::: snakeorm.expressions.SnakeOrder

::: snakeorm.expressions.SnakeValue

::: snakeorm.expressions.SnakeSubquery

::: snakeorm.expressions.SnakeFunc

::: snakeorm.expressions.SnakeCase

::: snakeorm.expressions.SnakeCoalesce

::: snakeorm.expressions.SnakeNullIf

::: snakeorm.expressions.SnakeCast

::: snakeorm.expressions.SnakeDateShift

::: snakeorm.expressions.SnakeDatePart

## Text functions

Seven scalar functions the three engines translate. What one of them cannot do is DECLARED with a reason, never left out — silence and 'not supported' would be indistinguishable.

```python
from snakeorm import SnakeQuery
from snakeorm.expressions import snake_concat, snake_length, snake_lower, snake_substring

rows = session.select(
    SnakeQuery(User).filter(snake_length(User.name) > 3),
    snake_lower(User.name),
    snake_concat(User.name, " <", User.email, ">"),
    snake_substring(User.email, 1, 5),
)
```

## Date functions

`DATE_TRUNC` and `EXTRACT` run where the engine has them and are REFUSED where it does not, and the two are not refused in the same places. `DATE_TRUNC` is PostgreSQL alone: MySQL and SQLite both declare they have none, so the plan stops instead of emitting SQL the engine would reject. `EXTRACT` is translated by PostgreSQL and MySQL, and only SQLite stops it. Naming one engine as "the one without them" would have been the tidier sentence and the wrong one — the refusal is per function, which is exactly why each dialect answers for it separately.

The part is a `SnakeDatePart`, not a string, and that is the point of the enum: it fixes the vocabulary to the parts the engines agree on, so the same call means the same thing on the three. Handed a `str`, the emitter reads a `.value` off it and dies of an `AttributeError` — a Python error where a readable refusal belongs, which is why the type is the one that keeps you out of it.

```python
from snakeorm import SnakeDatePart, SnakeQuery
from snakeorm.expressions import snake_date_trunc, snake_extract

rows = session.select(
    SnakeQuery(Visit),
    snake_date_trunc(SnakeDatePart.MONTH, Visit.created_at),  # PostgreSQL only
    snake_extract(SnakeDatePart.YEAR, Visit.created_at),      # PostgreSQL and MySQL
)
# On MySQL the first one stops the plan with a SnakeDialectError:
#   MySQLDialect cannot translate DATE_TRUNC: MySQL has no DATE_TRUNC. Reach for it through
#   `raw()` with the engine's own spelling.
# On SQLite BOTH stop, each naming its own function.
```

## Rounding and magnitude

`ABS` and `ROUND` ship with every build of every engine. Their absence from SQLite's table was bug #34, and that is exactly why a missing function has to be declared rather than left blank.

Asking `ROUND` for decimal places works on the three, and getting there took a dialect saying so: PostgreSQL has `ROUND(double precision)` and `ROUND(numeric, int)` and nothing in between, so it declares the type its two-argument form wants and the emitter casts. You write the same call everywhere.

```python
from snakeorm import SnakeQuery
from snakeorm.expressions import snake_abs, snake_round

rows = session.select(
    SnakeQuery(Reading),
    snake_abs(Reading.delta),        # the magnitude, sign dropped
    snake_round(Reading.amount),     # nearest whole number
    snake_round(Reading.amount, 2),  # to N places, on the three since bug #34 closed
)
```

## Maths that depend on the build

The three translate them, and on SQLite they are a COMPILE-TIME option (`ENABLE_MATH_FUNCTIONS`): a build without it answers `no such function: ceil` at runtime. That cannot be a capability — a capability is answered by the dialect class, which does not know which library got linked.

```python
from snakeorm import SnakeQuery
from snakeorm.expressions import snake_ceil, snake_floor, snake_power, snake_sqrt

rows = session.select(
    SnakeQuery(Reading),
    snake_ceil(Reading.amount),               # -8.76 -> -8, towards zero
    snake_floor(Reading.amount),              # -8.76 -> -9, away from zero
    snake_sqrt(snake_power(Reading.delta, 2)),  # the magnitude, the long way round
)
```

::: snakeorm.expressions.SnakeWindow

::: snakeorm.expressions.SnakeFrame

::: snakeorm.expressions.SnakeFrameBound

::: snakeorm.expressions.SnakeFrameMode

::: snakeorm.expressions.SNAKE_CURRENT_ROW

::: snakeorm.expressions.snake_rows

::: snakeorm.expressions.snake_range

::: snakeorm.expressions.snake_preceding

::: snakeorm.expressions.snake_following
::: snakeorm.expressions.snake_case

::: snakeorm.expressions.snake_coalesce

::: snakeorm.expressions.snake_nullif

::: snakeorm.expressions.snake_cast

::: snakeorm.expressions.snake_date_add

::: snakeorm.expressions.snake_date_sub

::: snakeorm.expressions.snake_substring

::: snakeorm.expressions.snake_replace

::: snakeorm.expressions.snake_ceil

::: snakeorm.expressions.snake_floor

::: snakeorm.expressions.snake_sqrt

::: snakeorm.expressions.snake_power

## Composite IN

::: snakeorm.expressions.snake_keys

::: snakeorm.expressions.snake_key

::: snakeorm.expressions.SnakeKeys

::: snakeorm.expressions.SnakeKey

## Aggregates

`string_agg` joins a group's values into one string. The `order_by` inside the call is not cosmetic: without it the order within a group belongs to the engine, and the three would answer differently for a reason that has nothing to do with your query.

```python
from snakeorm import SnakeQuery
from snakeorm.expressions import string_agg

rows = session.select(
    SnakeQuery(Sale).group_by(Sale.region).order_by(Sale.region.asc()),
    Sale.region,
    string_agg(Sale.seller, ",", order_by=[Sale.seller.asc()]),
)
# postgres string_agg   mysql GROUP_CONCAT   sqlite group_concat  -> one answer
```

::: snakeorm.expressions.SnakeStringAgg

::: snakeorm.expressions.string_agg

::: snakeorm.expressions.count

::: snakeorm.expressions.sum_

::: snakeorm.expressions.avg

::: snakeorm.expressions.min_

::: snakeorm.expressions.max_

## Window functions

::: snakeorm.expressions.row_number

::: snakeorm.expressions.rank

::: snakeorm.expressions.dense_rank

::: snakeorm.expressions.lag

::: snakeorm.expressions.lead

## Prefetch

::: snakeorm.fields.SnakePrefetch

::: snakeorm.fields.SnakePrefetchHop

