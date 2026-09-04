# Índices y constraints

```python
from typing import ClassVar

from snakeorm import (
    SnakeColumn, SnakeIndex, SnakeModel, snake_auto, snake_check, snake_checks,
    snake_indexes, snake_int, snake_model, snake_str,
)

@snake_model(table="people")
class Person(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    age: SnakeColumn[int] = snake_int()
    email: SnakeColumn[str] = snake_str()
    surname: SnakeColumn[str] = snake_str()
    name: SnakeColumn[str] = snake_str()

    SnakeIndexes: ClassVar[list[SnakeIndex]] = [SnakeIndex(email, unique=True)]

snake_checks(Person, snake_check(Person.age >= 18, name="adult"))
```

Los índices se pueden declarar **dentro** del cuerpo de la clase, con la lista `SnakeIndexes`. Los
CHECK y los índices parciales no: una condición como `Person.age >= 18` necesita que `Person` ya
exista como clase para que el descriptor devuelva una expresión tipada, así que van **fuera**, con
`snake_checks()` y `snake_indexes()`.

!!! warning "Un `SnakeIndex` recibe COLUMNAS, nunca sus nombres"

    `SnakeIndex(Person.email)` fuera del cuerpo, `SnakeIndex(email)` dentro — nunca
    `SnakeIndex("email")`. Una cadena no la comprueba nadie: renombrar la columna la dejaría
    apuntando en silencio a una columna que ya no existe.

## CHECK constraints

```python
snake_checks(
    Person,
    snake_check(Person.age >= 18, name="adult"),
    snake_check(Person.email.like("%@%")),
)
```

La condición es **la misma `SnakeCondition` que usa `.filter()`**: mypy y pyright la comprueban; si
renombras la columna, deja de compilar. Sin `name=`, el nombre es determinista: `ck_people_age`.

!!! warning "Dos CHECK sobre la misma columna necesitan un `name=`"

    Determinista quiere decir que sale de la tabla y de la columna, y de nada más, así que
    `snake_check(Person.age >= 18)` y `snake_check(Person.age <= 120)` salen las dos
    `ck_people_age`. Declararlas no levanta nada: el DDL lleva el nombre dos veces y quien para la
    migración es el MOTOR — PostgreSQL contesta `check constraint "ck_people_age" already exists`.
    Ése es el extremo malo de la tubería para enterarse, así que ponle `name=` a la segunda.

!!! note "Las subconsultas se rechazan al declarar, no al migrar"

    Un `EXISTS` o una subconsulta dentro de un CHECK no cabe en un fichero de migración, y PostgreSQL
    tampoco lo admite. Rechazarlo al escribirlo es corrección, no limitación.

## Índices

```python
snake_indexes(
    Person,
    SnakeIndex(Person.surname, Person.name),
    SnakeIndex(Person.email, unique=True),
)
```

O el atajo por columna, para el caso simple:

```python
surname: SnakeColumn[str] = snake_str(index=True)
```

### Índices parciales

```python
snake_indexes(
    Customer,
    SnakeIndex(Customer.name, where=Customer.closed_on.is_null()),
)
```

Solo indexa las filas activas — en un motor que TENGA índices parciales. MySQL/MariaDB no tiene
`WHERE` en su `CREATE INDEX`, y ahí la misma declaración se va por dos caminos distintos: un índice
de búsqueda se **degrada**, se tira el `WHERE` y el índice se crea sobre la tabla entera (encuentra
las mismas filas y ocupa más, y la sesión lo dice una vez); un índice UNIQUE parcial **para el
plan**, porque ensancharlo prohibiría filas que tu dominio admite, que es otro esquema y no uno más
lento. Los dos están contados en [límites](../reference/limits.es.md).

### Método de índice

```python
from snakeorm.metadata import SnakeIndexMethod

snake_indexes(Document, SnakeIndex(Document.content, method=SnakeIndexMethod.GIN))
```

`BTREE`, `HASH`, `GIN`, `GIST`, `BRIN`. El enum es uno para todos los motores; lo que cada motor
ACEPTA no lo es, y el dialecto lanza `SnakeDialectError` con lo que no sabe traducir en vez de
darte calladamente un índice corriente que contesta otra pregunta:

| Motor | Qué acepta |
|---|---|
| PostgreSQL | todos |
| MySQL/MariaDB | `BTREE` y `HASH`. `GIN`, `GIST` y `BRIN` son de Postgres y se rechazan |
| SQLite | solo `BTREE` — tiene UNA sola clase de índice, así que rechaza cualquier otro |

`BTREE` se omite del SQL por ser el defecto, y esa omisión es justo lo que lo hace el portable: no
llega nunca a la traducción del dialecto, así que una declaración con `BTREE` —o sin `method=`—
corre en los tres. Cualquier otra cosa estrecha el modelo a los motores que la tengan, y éste es el
sitio donde decirlo cuesta una palabra.

## Unicidad: constraint o índice

| Cómo lo pides | Qué sale | Nombre |
|---|---|---|
| `snake_column(unique=True)` | `CONSTRAINT ... UNIQUE` | `uq_table_column` |
| `SnakeIndex(..., unique=True)` | `CONSTRAINT ... UNIQUE` | `uq_table_columns` |
| `SnakeIndex(..., unique=True, where=...)` | `CREATE UNIQUE INDEX` | `ix_table_columns` |

Las dos primeras producen **el mismo objeto**: la constraint DICE la regla del dominio; el índice es
solo cómo se implementa. La tercera es la excepción, y tiene motivo del motor: PostgreSQL **no
admite** `UNIQUE ... WHERE`, así que un único parcial solo existe como índice.

!!! info "En SQLite la constraint se traduce a índice único"

    SQLite no tiene `ALTER TABLE ... ADD CONSTRAINT`. Un `CREATE UNIQUE INDEX` da la misma garantía;
    el nombre no cambia. Ver [dialectos](../engines/dialects.es.md).

## Qué índice falta: `snakeorm advise`

```bash
uv run snakeorm advise --models myapp.models
```

Audita el esquema y lista las claves ajenas **sin índice** —las columnas que más se filtran y se
juntan— con el arreglo al lado de cada una:

```text
2 FK(s) without an index (worth indexing):
  orders.customer_id  ->  snake_column(index=True)
  lines.order_id  ->  snake_column(index=True)
```

Es estático: lee la metadata, no abre ninguna conexión y no lanza ninguna consulta. La otra mitad, la
viva —qué columnas filtraron las consultas que de verdad emitiste, ordenadas por la peor duración—
está en el [panel de debug](debugging.es.md).

---

Siguiente: [consultas avanzadas](advanced-queries.es.md).
