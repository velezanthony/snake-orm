# Motores: dialectos, drivers y capacidades

Dos ejes que nunca se mezclan: el **dialecto** decide cómo se ESCRIBE el SQL,
el **driver** cómo se EJECUTA. Un modelo no ve ninguno de los dos.

Encima está el catálogo de capacidades: cada dialecto contesta a TODO `Cap` con `Full`,
`Degraded(motivo)` o `Nope(motivo)`, y el que se olvide de una entrada no arranca. De ahí salen a la
vez la decisión que toma el plan y el aviso que recibes al abrir la sesión.

!!! note "De dónde sale este texto"

    Todo lo que hay bajo los títulos se genera desde los docstrings del propio paquete, en cada
    build.

## Conexión

::: snakeorm.connection.SnakeConnectionConfig

::: snakeorm.connection.SnakeBackend

## Dialectos

::: snakeorm.dialects.SnakeDialect

::: snakeorm.dialects.PostgresDialect

::: snakeorm.dialects.MySQLDialect

::: snakeorm.dialects.SQLiteDialect

## Catálogo de capacidades

::: snakeorm.dialects.capabilities.Cap

::: snakeorm.dialects.capabilities.Full

::: snakeorm.dialects.capabilities.Degraded

::: snakeorm.dialects.capabilities.Nope

::: snakeorm.dialects.capabilities.SnakeCapabilities

::: snakeorm.dialects.capabilities.SnakeSyntax

::: snakeorm.dialects.capabilities.SnakeLimits

::: snakeorm.dialects.capabilities.AlterColumnStyle

::: snakeorm.dialects.capabilities.EmptyInsertStyle

## Drivers síncronos

::: snakeorm.drivers.SnakeDriver

::: snakeorm.drivers.PsycopgDriver

::: snakeorm.drivers.PyMySQLDriver

::: snakeorm.drivers.SQLiteDriver

::: snakeorm.drivers.SnakePool
::: snakeorm.drivers.psycopg_pool

::: snakeorm.drivers.LoggingDriver

::: snakeorm.drivers.TimeoutDriver

## Drivers asíncronos

::: snakeorm.drivers.AsyncDriver

::: snakeorm.drivers.AsyncPsycopgDriver

::: snakeorm.drivers.AsyncPyMySQLDriver

::: snakeorm.drivers.AsyncSQLiteDriver

::: snakeorm.drivers.AsyncSnakePool

::: snakeorm.drivers.ThreadedAsyncDriver

::: snakeorm.drivers.AsyncLoggingDriver

::: snakeorm.drivers.AsyncTimeoutDriver

## Tipos personalizados

::: snakeorm.core.converters.register_converter

