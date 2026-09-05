# Engines: dialects, drivers and capabilities

Two axes that never mix: the **dialect** decides how the SQL is written, the
**driver** decides how it is executed. A model never sees either.

On top of that sits the capability catalogue: every dialect answers the WHOLE of `Cap` with `Full`,
`Degraded(reason)` or `Nope(reason)`, and one that forgets an entry fails on import. From it come
both the decision the plan takes and the warning you get when the session opens.

!!! note "Where this text comes from"

    Everything below the headings is generated from the package's own docstrings, on every build.

## Connection

::: snakeorm.connection.SnakeConnectionConfig

::: snakeorm.connection.SnakeBackend

## Dialects

::: snakeorm.dialects.SnakeDialect

::: snakeorm.dialects.PostgresDialect

::: snakeorm.dialects.MySQLDialect

::: snakeorm.dialects.SQLiteDialect

## Capability catalogue

::: snakeorm.dialects.capabilities.Cap

::: snakeorm.dialects.capabilities.Full

::: snakeorm.dialects.capabilities.Degraded

::: snakeorm.dialects.capabilities.Nope

::: snakeorm.dialects.capabilities.SnakeCapabilities

::: snakeorm.dialects.capabilities.SnakeSyntax

::: snakeorm.dialects.capabilities.SnakeLimits

::: snakeorm.dialects.capabilities.AlterColumnStyle

::: snakeorm.dialects.capabilities.EmptyInsertStyle

## Synchronous drivers

::: snakeorm.drivers.SnakeDriver

::: snakeorm.drivers.PsycopgDriver

::: snakeorm.drivers.PyMySQLDriver

::: snakeorm.drivers.SQLiteDriver

::: snakeorm.drivers.SnakePool
::: snakeorm.drivers.psycopg_pool

::: snakeorm.drivers.LoggingDriver

::: snakeorm.drivers.TimeoutDriver

## Asynchronous drivers

::: snakeorm.drivers.AsyncDriver

::: snakeorm.drivers.AsyncPsycopgDriver

::: snakeorm.drivers.AsyncPyMySQLDriver

::: snakeorm.drivers.AsyncSQLiteDriver

::: snakeorm.drivers.AsyncSnakePool

::: snakeorm.drivers.ThreadedAsyncDriver

::: snakeorm.drivers.AsyncLoggingDriver

::: snakeorm.drivers.AsyncTimeoutDriver

## Custom types

::: snakeorm.core.converters.register_converter

