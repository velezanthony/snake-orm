# Construir consultas

Una consulta es un **valor**: no ejecuta, no tiene conexión, y cada método
devuelve una nueva. Eso es lo que permite que la misma consulta la ejecute la sesión síncrona o la
asíncrona sin saber cuál — y lo que hace que apilar fragmentos funcione sin ninguna pieza extra.

Comparar una columna no da un `bool`. `User.age > 18` es una `SnakeCondition`, y ahí está todo el
truco de la navegación profunda tipada.

!!! note "De dónde sale este texto"

    Todo lo que hay bajo los títulos se genera desde los docstrings del propio paquete, en cada
    build.

## Consultas

::: snakeorm.query.SnakeQuery

::: snakeorm.query.SnakeJoinedQuery

::: snakeorm.query.SnakeJoin

::: snakeorm.query.SnakeCompound

::: snakeorm.query.SnakeSetOp

::: snakeorm.query.SnakeRecursive

## Expresiones

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

## Funciones de texto

Siete funciones escalares que traducen los tres motores. Lo que uno no puede hacer se DECLARA con motivo, nunca se omite — el silencio y «no soportada» serían indistinguibles.

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

## Funciones de fecha

`DATE_TRUNC` y `EXTRACT` corren donde el motor las tiene y se RECHAZAN donde no, y a las dos no se las rechaza en los mismos sitios. `DATE_TRUNC` es solo de PostgreSQL: MySQL y SQLite declaran las dos que no la tienen, así que el plan se para en vez de emitir SQL que el motor iba a rechazar. `EXTRACT` la traducen PostgreSQL y MySQL, y solo SQLite la para. Nombrar a un motor como «el que no las tiene» habría sido la frase más limpia y la equivocada — el rechazo es por función, que es justo por lo que cada dialecto contesta por ella aparte.

La parte es un `SnakeDatePart`, no una cadena, y ahí está el sentido del enum: fija el vocabulario a las partes en las que los motores coinciden, así que la misma llamada significa lo mismo en los tres. Con un `str`, el emisor le lee un `.value` y muere de un `AttributeError` — un error de Python donde toca un rechazo legible, y por eso el tipo es lo que te mantiene fuera de ahí.

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

## Redondeo y magnitud

`ABS` y `ROUND` vienen en todos los builds de todos los motores. Su ausencia de la tabla de SQLite fue el bug #34, y por eso justamente una función que falta hay que declararla en vez de dejarla en blanco.

Pedirle a `ROUND` decimales funciona en los tres, y llegar ahí requirió que un dialecto lo dijera: PostgreSQL tiene `ROUND(double precision)` y `ROUND(numeric, int)` y nada en medio, así que declara el tipo que quiere su forma de dos argumentos y el emisor castea. Tú escribes la misma llamada en todas partes.

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

## Matemáticas que dependen del build

Los tres las traducen, y en SQLite son una opción de COMPILACIÓN (`ENABLE_MATH_FUNCTIONS`): un build sin ella contesta `no such function: ceil` en ejecución. Eso no puede ser una capacidad — una capacidad la contesta la clase del dialecto, que no sabe qué biblioteca se enlazó.

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

::: snakeorm.expressions.snake_lower

::: snakeorm.expressions.snake_upper

::: snakeorm.expressions.snake_trim

::: snakeorm.expressions.snake_length

::: snakeorm.expressions.snake_concat

::: snakeorm.expressions.snake_date_trunc

::: snakeorm.expressions.snake_extract

::: snakeorm.expressions.snake_abs

::: snakeorm.expressions.snake_round

## IN compuesto

::: snakeorm.expressions.snake_keys

::: snakeorm.expressions.snake_key

::: snakeorm.expressions.SnakeKeys

::: snakeorm.expressions.SnakeKey

## Agregados

`string_agg` une los valores de un grupo en una cadena. El `order_by` de dentro de la llamada no es cosmético: sin él, el orden dentro del grupo es cosa del motor y los tres contestarían distinto por un motivo que no tiene que ver con tu consulta.

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

## Funciones de ventana

::: snakeorm.expressions.row_number

::: snakeorm.expressions.rank

::: snakeorm.expressions.dense_rank

::: snakeorm.expressions.lag

::: snakeorm.expressions.lead

## Prefetch

::: snakeorm.fields.SnakePrefetch

::: snakeorm.fields.SnakePrefetchHop

