# Relaciones

```python
from snakeorm import (
    SnakeColumn, SnakeModel, SnakeToMany, SnakeToOne, SnakeFkAction,
    snake_auto, snake_column, snake_int, snake_link, snake_model, snake_str,
    snake_to_many, snake_to_one,
)

@snake_model(table="countries")
class Country(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    brands: SnakeToMany["Brand"] = snake_to_many("country")

@snake_model(table="brands")
class Brand(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    country_id: SnakeColumn[int] = snake_int()
    country: SnakeToOne[Country] = snake_to_one(country_id)
    cars: SnakeToMany["Car"] = snake_to_many("brand")  # inverse of Car.brand

@snake_model(table="cars")
class Car(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    brand_id: SnakeColumn[int] = snake_int()  # local FK column
    electric: SnakeColumn[bool] = snake_column()
    brand: SnakeToOne[Brand] = snake_to_one(brand_id, on_delete=SnakeFkAction.CASCADE)

snake_link()  # MANDATORY: once, after importing ALL models
```

!!! warning "Si la clave foránea acepta NULL, la relación se declara opcional"

    ```python
    category_id: SnakeColumn[int | None]       = snake_int()
    category:    SnakeToOne["Category | None"] = snake_to_one(category_id)
    ```

    Las dos tienen que decir lo mismo, y el linker lo **exige al arrancar**. Una clave que admite
    NULL con una relación no opcional hace que `post.category.name` compile y luego sea un
    `AttributeError` en producción; una clave `NOT NULL` declarada opcional te obliga a tratar un
    caso imposible, ruido que esconde los `None` de verdad.

## A-uno (clave foránea)

- **La columna FK se declara aparte** (`brand_id`); `brand` es la relación que la usa. FK compuesta
  = varias columnas por posición: `snake_to_one(a_id, b_id)`.
- **El destino sale de la anotación** `SnakeToOne[Brand]`, nunca de un string.

`on_delete`/`on_update` toman `SnakeFkAction` (`NO_ACTION`, `CASCADE`, `SET_NULL`, `RESTRICT`,
`SET_DEFAULT`), agnóstico del motor. Cambiarlos **genera migración**.

## A-muchos (la inversa)

```python
cars: SnakeToMany["Car"] = snake_to_many("brand")
```

El argumento es el **nombre de la relación a-uno** del otro lado (`Car.brand`), no el de la
columna. Las comillas en `"Car"` son un forward reference; `snake_link()` lo resuelve al final.

## Muchos-a-muchos

Con un modelo puente explícito, sin tabla oculta:

```python
from snakeorm import snake_to_many_through

@snake_model(table="post_tag")
class PostTag(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    post_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne["Post"] = snake_to_one(post_id)
    tag: SnakeToOne["Tag"] = snake_to_one(tag_id)

@snake_model(table="posts")
class Post(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    tags: SnakeToMany["Tag"] = snake_to_many_through(
        through="PostTag", via="post", to="tag"
    )
```

El puente es un modelo normal: tiene tabla, migraciones y sus propias columnas si las necesitas.

## Enlazar

```python
snake_link()  # once, after importing ALL models
```

Sin esto las relaciones no tienen destino. Es una pasada explícita para que el resultado sea **el
mismo independientemente del orden de imports**.

## Navegar

Filtrar por un camino profundo no carga nada; los JOIN salen del camino y el type-checker comprueba
cada salto:

```python
from snakeorm import SnakeQuery

SnakeQuery(Car).filter(Car.brand.country.name == "Spain")
```

## Cargar

```python
session.all(SnakeQuery(Car).include(Car.brand))          # to-one -> JOIN
session.all(SnakeQuery(Car).include(Car.brand.country))  # two JOINs
session.all(SnakeQuery(Brand).include(Brand.cars))       # to-many -> a second query
```

Un a-uno se trae con `JOIN`; un a-muchos con una **segunda consulta** (un JOIN multiplicaría las
filas del padre). Esa segunda consulta se trocea por el tope de marcadores del motor —65.535 en
PostgreSQL y MySQL, 32.766 en SQLite, y la mitad con una FK de dos columnas—, así que un conjunto de
padres muy grande cuesta varias consultas, nunca una por padre.

!!! danger "Acceder a una relación no cargada lanza `SnakeRelationshipNotLoaded`"

    No dispara una consulta a tus espaldas. El N+1 es imposible por defecto.

    ```python
    car = session.first(SnakeQuery(Car))
    car.brand
    # SnakeRelationshipNotLoaded: Relation 'brand' was not loaded.
    #                        Use .include(Car.brand) in the query.
    ```

## Anidar: `SnakePrefetch`

Una colección no expone las relaciones de su hijo, así que anidar más allá de un a-muchos se
**declara**, no se navega:

```python
from snakeorm import SnakePrefetch

session.all(SnakeQuery(Country).include(
    SnakePrefetch(Country.brands).then(Brand.cars)
))  # one query per LEVEL, never one per parent

session.all(SnakeQuery(Brand).include(
    SnakePrefetch(Brand.cars).filter(Car.electric == True)
))  # a brand with no electric car still comes back, with cars == []
```

`.then()` solo acepta relaciones del modelo del nivel actual, y el `.filter()` de aquí no es el
`query.filter()`: acota QUÉ hijos se cargan, nunca tira padres.

## Existencia

"Marcas con algún coche eléctrico", sin traer los coches:

```python
SnakeQuery(Brand).filter(Brand.cars.any(Car.electric == True))
```

Emite un `EXISTS` correlacionado; la navegación profunda funciona dentro igual que fuera.

## Meter una colección en la proyección con JOIN

`include()` te da los hijos como lista. Cuando lo que quieres son las FILAS del hijo en la proyección
—una fila de salida por hijo— el JOIN se pide explícito:

```python
from snakeorm import SnakeJoin

joined = SnakeQuery(Brand).join(Brand.cars, how=SnakeJoin.LEFT)
session.select(joined, Brand.id, joined.right.id, joined.right.electric)
```

Las columnas del hijo salen de `joined.right`, que lleva el alias del JOIN. Como el JOIN multiplica
filas, `SnakeJoinedQuery` solo proyecta: no tiene `.all()`/`.first()`.

---

Siguiente: [herencia](inheritance.es.md).
