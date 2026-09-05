# Declarar modelos

Todo lo que hace falta para convertir una clase de Python en una tabla: el
decorador que la compila, los field specifiers que añaden información SQL a cada columna, y los
descriptores que dan a las relaciones su navegación tipada.

La regla que lo gobierna todo: **el tipo viene de Python**. Un specifier nunca cambia el tipo ni
contradice la anotación — solo añade lo que SQL necesita saber.

!!! note "De dónde sale este texto"

    Todo lo que hay bajo los títulos se genera desde los docstrings del propio paquete, en cada
    build.

## Modelo y vista

Una VISTA es un modelo cuyo cuerpo es una consulta, así que se renderiza en el dialecto DESTINO — una vista compuesta se escribe de nuevo por motor. Donde no hay `CREATE OR REPLACE VIEW`, el emisor hace `DROP` + `CREATE`, que es capacidad declarada y no una suposición.

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

## Decoradores

::: snakeorm.decorators.snake_model

::: snakeorm.decorators.snake_view

::: snakeorm.decorators.snake_abstract

::: snakeorm.decorators.snake_db_first

::: snakeorm.decorators.snake_table

::: snakeorm.decorators.snake_result

::: snakeorm.decorators.snake_row

::: snakeorm.decorators.snake_function

::: snakeorm.decorators.snake_trigger

## Descriptores

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

## Índices y constraints

::: snakeorm.fields.SnakeIndex

::: snakeorm.metadata.SnakeIndexMethod

::: snakeorm.fields.snake_indexes

::: snakeorm.fields.snake_check

::: snakeorm.fields.snake_checks

## Enlazado

::: snakeorm.linker.snake_link

::: snakeorm.registry.SnakeRegistry
::: snakeorm.registry.registry

## Enums de declaración

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

## Metadata compilada

El grafo que el compilador construye UNA vez y que todo lo demás lee. No se escriben a mano, pero son
públicos porque una migración, un check o un trigger que inspecciones en runtime te los entrega.

::: snakeorm.metadata.SnakeRelationshipKind

::: snakeorm.metadata.SnakeThroughInfo

::: snakeorm.metadata.SnakeCheckInfo

::: snakeorm.metadata.SnakeTriggerInfo

::: snakeorm.metadata.SnakeTriggerEvent

::: snakeorm.metadata.SnakeTriggerTiming
