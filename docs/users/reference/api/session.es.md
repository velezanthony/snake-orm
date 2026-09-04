# Sesiones

La capa con *color*: coge una consulta (que no lo tiene) y la ejecuta. Las
dos sesiones exponen la misma superficie y consumen el mismo plan de ejecución — incluidos los
mismos mensajes de error, que un test compara.

!!! note "De dónde sale este texto"

    Todo lo que hay bajo los títulos se genera desde los docstrings del propio paquete, en cada
    build.

## Sesiones

::: snakeorm.session.SnakeSession

::: snakeorm.session.AsyncSession

::: snakeorm.session.snake_session

::: snakeorm.session.SnakeIsolation

## Reintentos

::: snakeorm.session.with_retry

::: snakeorm.session.is_transient

## Instantes

::: snakeorm.times.SnakeUtc

::: snakeorm.times.utc_now

::: snakeorm.times.parse_utc

::: snakeorm.times.to_utc

::: snakeorm.times.utc_from_zone

## Señales

::: snakeorm.core.signals.SnakeSignal
::: snakeorm.core.signals.snake_on

