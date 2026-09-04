# Errores y avisos

Este ORM **grita**: no arregla por su cuenta ni degrada en silencio. Cada
excepción de aquí abajo marca una decisión que tiene que tomar alguien, y su mensaje dice qué
escribir en su lugar — no solo qué ha ido mal.

`SnakeWarning` es un `UserWarning` propio para que
`filterwarnings("ignore", category=SnakeWarning)` silencie el ORM y nada más.

!!! note "De dónde sale este texto"

    Todo lo que hay bajo los títulos se genera desde los docstrings del propio paquete, en cada
    build.

## Base

::: snakeorm.core.exceptions.SnakeError

## Declaración

::: snakeorm.core.exceptions.SnakeModelError

::: snakeorm.core.exceptions.SnakeModelDefinitionError

::: snakeorm.core.exceptions.SnakeRegistryError

::: snakeorm.core.exceptions.SnakeDtoError

::: snakeorm.core.exceptions.SnakeUnknownColumn

::: snakeorm.core.exceptions.SnakeUnknownRelationship

::: snakeorm.core.exceptions.SnakeUnlinkedRelationship

## Ejecución

::: snakeorm.core.exceptions.SnakeValueError

::: snakeorm.core.exceptions.SnakeEmitError
::: snakeorm.core.exceptions.SnakeNodeError

::: snakeorm.core.exceptions.SnakeRelationshipNotLoaded

::: snakeorm.core.exceptions.SnakeAggregateNotLoaded

::: snakeorm.core.exceptions.SnakeColumnNotLoaded

::: snakeorm.core.exceptions.SnakeUnsupportedFeature

## Restricciones

Una restricción que rechaza una escritura lanza la MISMA excepción en los tres motores. Cada una se clasifica por el código que manda el motor —un SQLSTATE, un errno de MySQL o un nombre de resultado extendido de SQLite—, nunca por el mensaje y nunca por la clase de excepción del driver: en MySQL un `CHECK` llega como `OperationalError` y los otros tres como `IntegrityError`.

La excepción del driver va encadenada, no escondida. Se queda en `__cause__` y, dicha por su nombre, en `driver_error`; `code` dice qué código decidió el subtipo.

```python
from snakeorm import SnakeIntegrityError, SnakeUniqueViolation

try:
    session.add(User(email="taken@example.com"))
    session.commit()
except SnakeUniqueViolation as refused:
    # the same exception on PostgreSQL, MySQL and SQLite
    print(refused.code)          # "23505" | 1062 | "SQLITE_CONSTRAINT_UNIQUE"
    print(refused.driver_error)  # the DBAPI's own, also in __cause__
except SnakeIntegrityError:
    # the coarse catch: any constraint at all
    session.rollback()
```

::: snakeorm.core.exceptions.SnakeIntegrityError

::: snakeorm.core.exceptions.SnakeUniqueViolation

::: snakeorm.core.exceptions.SnakeForeignKeyViolation

::: snakeorm.core.exceptions.SnakeNotNullViolation

::: snakeorm.core.exceptions.SnakeCheckViolation

## Motor y migraciones

::: snakeorm.core.exceptions.SnakeDialectError

::: snakeorm.core.exceptions.SnakeMigrationError

::: snakeorm.core.exceptions.SnakeConfigError

::: snakeorm.core.exceptions.SnakePoolTimeout

## Avisos

::: snakeorm.core.exceptions.SnakeWarning

