# Sessions

The layer with *colour*: it takes a query (which has none) and runs it. The
two sessions expose the same surface and consume the same execution plan — including the same error
messages, which a test compares.

!!! note "Where this text comes from"

    Everything below the headings is generated from the package's own docstrings, on every build.

## Sessions

::: snakeorm.session.SnakeSession

::: snakeorm.session.AsyncSession

::: snakeorm.session.snake_session

::: snakeorm.session.SnakeIsolation

## Retries

::: snakeorm.session.with_retry

::: snakeorm.session.is_transient

## Instants

::: snakeorm.times.SnakeUtc

::: snakeorm.times.utc_now

::: snakeorm.times.parse_utc

::: snakeorm.times.to_utc

::: snakeorm.times.utc_from_zone

## Signals

::: snakeorm.core.signals.SnakeSignal
::: snakeorm.core.signals.snake_on

