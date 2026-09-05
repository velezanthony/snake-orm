# Relationships

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

!!! warning "If the foreign key accepts NULL, the relationship is declared optional"

    ```python
    category_id: SnakeColumn[int | None]       = snake_int()
    category:    SnakeToOne["Category | None"] = snake_to_one(category_id)
    ```

    Both must say the same thing, and the linker **demands it at startup**. A nullable key with a
    non-optional relationship makes `post.category.name` compile and then be an `AttributeError` in
    production; a `NOT NULL` key declared optional forces you to handle a case that cannot happen,
    noise that hides the real `None`s.

## To-one (foreign key)

- **The FK column is declared separately** (`brand_id`); `brand` is the relationship that uses it. A
  composite FK is several columns by position: `snake_to_one(a_id, b_id)`.
- **The target comes from the annotation** `SnakeToOne[Brand]`, never from a string.

`on_delete`/`on_update` take `SnakeFkAction` (`NO_ACTION`, `CASCADE`, `SET_NULL`, `RESTRICT`,
`SET_DEFAULT`), engine-agnostic. Changing them **generates a migration**.

## To-many (the inverse)

```python
cars: SnakeToMany["Car"] = snake_to_many("brand")
```

The argument is the **name of the to-one relationship** on the other side (`Car.brand`), not the
column's. The quotes in `"Car"` are a forward reference; `snake_link()` resolves it at the end.

## Many-to-many

With an explicit bridge model, no hidden table:

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

The bridge is a normal model: it has a table, migrations and its own columns if it needs them.

## Linking

```python
snake_link()  # once, after importing ALL models
```

Without this, relationships have no target. It's an explicit pass so the result is **the same
regardless of import order**.

## Navigating

Filtering by a deep path loads nothing; the JOINs come out of the path and the type-checker checks
every hop:

```python
from snakeorm import SnakeQuery

SnakeQuery(Car).filter(Car.brand.country.name == "Spain")
```

## Loading

```python
session.all(SnakeQuery(Car).include(Car.brand))          # to-one -> JOIN
session.all(SnakeQuery(Car).include(Car.brand.country))  # two JOINs
session.all(SnakeQuery(Brand).include(Brand.cars))       # to-many -> a second query
```

A to-one is fetched with a `JOIN`; a to-many with a **second query** (a JOIN would multiply the
parent rows). That second query is sliced by the engine's placeholder ceiling — 65,535 on PostgreSQL
and MySQL, 32,766 on SQLite, halved again by a two-column FK — so a very large parent set costs
several queries, never one per parent.

!!! danger "Accessing a relationship that isn't loaded raises `SnakeRelationshipNotLoaded`"

    It doesn't fire a query behind your back. N+1 is impossible by default.

    ```python
    car = session.first(SnakeQuery(Car))
    car.brand
    # SnakeRelationshipNotLoaded: Relation 'brand' was not loaded.
    #                        Use .include(Car.brand) in the query.
    ```

## Nesting: `SnakePrefetch`

A collection doesn't expose its child's relationships, so nesting past a to-many is **declared**, not
navigated:

```python
from snakeorm import SnakePrefetch

session.all(SnakeQuery(Country).include(
    SnakePrefetch(Country.brands).then(Brand.cars)
))  # one query per LEVEL, never one per parent

session.all(SnakeQuery(Brand).include(
    SnakePrefetch(Brand.cars).filter(Car.electric == True)
))  # a brand with no electric car still comes back, with cars == []
```

`.then()` only accepts relationships of the model at the current level, and `.filter()` here is not
`query.filter()`: it narrows WHICH children get loaded, it never drops parents.

## Existence

"Brands with at least one electric car", without fetching the cars:

```python
SnakeQuery(Brand).filter(Brand.cars.any(Car.electric == True))
```

It emits a correlated `EXISTS`; deep navigation works inside just like outside.

## Joining a collection into the projection

`include()` gives you the children as a list. When you want the child's ROWS in the projection — one
output row per child — join explicitly:

```python
from snakeorm import SnakeJoin

joined = SnakeQuery(Brand).join(Brand.cars, how=SnakeJoin.LEFT)
session.select(joined, Brand.id, joined.right.id, joined.right.electric)
```

The child's columns come off `joined.right`, which carries the JOIN's alias. Because the JOIN
multiplies rows, `SnakeJoinedQuery` only projects: it has no `.all()`/`.first()`.

---

Next: [inheritance](inheritance.md).
