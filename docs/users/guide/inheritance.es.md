# Herencia

Tres formas:

| Forma | Tablas | Consultar la jerarquía junta |
|---|---|---|
| Base abstracta | Una por hija | No |
| Concreta | Una por hija | No (harían falta `UNION` a mano) |
| Polimórfica | **Una para todas** | Sí, y cada fila vuelve con su clase real |

## Base abstracta

La base **no** es tabla; solo aporta columnas:

```python
from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeUtc,
    snake_abstract,
    snake_auto,
    snake_datetimetz,
    snake_int,
    snake_model,
    snake_str,
)

@snake_abstract
class WithAudit(SnakeModel):
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)
    created_by: SnakeColumn[str | None] = snake_str()

@snake_model(table="orders")
class Order(WithAudit):
    id: SnakeColumn[int] = snake_auto()

@snake_model(table="invoices")
class Invoice(WithAudit):
    id: SnakeColumn[int] = snake_auto()
```

`orders` e `invoices` llevan cada una sus columnas de auditoría. `WithAudit` no genera nada y
consultarla lanza error. Es lo que quieres el 90% de las veces: compartir columnas sin compartir
identidad.

## Concreta

Igual, pero la base **sí** es tabla. Las columnas se duplican en las hijas, cada una por su cuenta:

```python
@snake_model(table="vehicles")
class Vehicle(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    plate: SnakeColumn[str] = snake_str()

@snake_model(table="trucks")
class Truck(Vehicle):
    payload_kg: SnakeColumn[int] = snake_int()
```

`trucks` tiene `id`, `plate` y `payload_kg`. Consultar `Vehicle` no ve los camiones.

## Polimórfica

Una tabla para toda la familia y una columna que dice qué es cada fila:

```python
from snakeorm import SnakeQuery, snake_discriminator, snake_link

@snake_model(table="animals")
class Animal(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_discriminator()
    name: SnakeColumn[str] = snake_str()

@snake_model(discriminator_value="dog")
class Dog(Animal):
    breed: SnakeColumn[str | None] = snake_str()

@snake_model(discriminator_value="cat")
class Cat(Animal):
    lives: SnakeColumn[int | None] = snake_int()

snake_link()  # MANDATORY: once, after importing ALL models
```

Tras `snake_link()`, una sola tabla `animals` con `id`, `kind`, `name`, `breed` y `lives`. La
llamada aquí sostiene el ejemplo, no es un trámite: lo que pliega las columnas de una hija dentro de
la tabla de la base es el ENLAZADO, así que hasta que corre `Animal` lleva solo lo que declaró
`Animal`, y el `CREATE TABLE` que escribiría una migración sale corto — sin ningún error, porque
todavía no hay nada mal. Las otras dos formas no la necesitan: no mueven ninguna columna de una
tabla a otra.

Consultar la **base** ve la jerarquía entera y cada fila vuelve con su **clase real**; consultar una
**hija** filtra sola:

```python
animals = session.all(SnakeQuery(Animal))
# [Dog(id=1, kind='dog', name='Toby', breed='mongrel'),
#  Cat(id=2, kind='cat', name='Fluffy', lives=9)]

dogs = session.all(SnakeQuery(Dog))  # WHERE kind = 'dog', automatic
```

El discriminador lo pone la **clase** (no lo pases al `__init__`):

```python
session.add(Dog(name="Toby", breed="mongrel"))  # no `kind=`
```

Por eso se declara con `snake_discriminator()` y no con un parámetro del decorador: solo un field
specifier lleva el `init=False` que leen mypy y pyright. No hay `inherits=Animal`: `class
Dog(Animal)` ya lo dice.

### Reglas

!!! warning "Las columnas propias de una hija tienen que admitir `NULL`"

    La tabla es UNA: `lives` de `Cat` existe también en las filas de `Dog`. Un `NOT NULL` haría
    imposible insertar un perro. Se comprueba al declarar el modelo.

!!! note "El discriminador se indexa solo"

    Toda consulta a una subclase lleva `WHERE kind = '...'`. Sin índice, cada lectura recorre la
    jerarquía entera.

!!! info "Un valor desconocido no rompe nada"

    Una fila con un discriminador que este proceso no conoce se hidrata como la clase **base**. Se
    pierden los campos de la subclase; no la fila.

### Migraciones

La tabla la crea la base, con la unión de columnas de la jerarquía — la unión que calculó
`snake_link()`. Las hijas **no** generan `CREATE TABLE` propio. Añadir una subclase es un
`AddColumn` por columna que aporte.

!!! danger "`snake_link()` tiene que haber corrido donde se use la jerarquía"

    No solo antes de `makemigrations`. Sin él la unión no se pliega jamás, y **nada lanza**: el
    `CREATE TABLE` sale corto, y una sesión hidrata un `Dog` cuyo `breed` lee `MISSING`. El mismo
    silencio por los dos lados. Enlaza donde se importan los modelos, una vez, y todos los lectores
    reciben la jerarquía entera.

---

Siguiente: [índices y constraints](indexes-and-constraints.es.md).
