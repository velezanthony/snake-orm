# Inheritance

Three forms:

| Form | Tables | Query the hierarchy together |
|---|---|---|
| Abstract base | One per child | No |
| Concrete | One per child | No (you'd need `UNION` by hand) |
| Polymorphic | **One for all** | Yes, and each row comes back with its real class |

## Abstract base

The base is **not** a table; it only contributes columns:

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

`orders` and `invoices` each carry their own audit columns. `WithAudit` generates nothing and
querying it raises. It's what you want 90% of the time: share columns without sharing identity.

## Concrete

Same, but the base **is** a table. The columns are duplicated in the children, each on its own:

```python
@snake_model(table="vehicles")
class Vehicle(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    plate: SnakeColumn[str] = snake_str()

@snake_model(table="trucks")
class Truck(Vehicle):
    payload_kg: SnakeColumn[int] = snake_int()
```

`trucks` has `id`, `plate` and `payload_kg`. Querying `Vehicle` doesn't see the trucks.

## Polymorphic

One table for the whole family and a column that says what each row is:

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

After `snake_link()`, a single `animals` table with `id`, `kind`, `name`, `breed` and `lives`. The
call is load-bearing here and not a formality: what folds a child's columns into the base's table is
the LINKING, so until it runs `Animal` carries only what `Animal` declared, and the `CREATE TABLE`
a migration writes comes out short — with no error, because nothing is wrong yet. The other two
forms do not need it; they never move a column from one table to another.

Querying the **base** sees the entire hierarchy and each row comes back with its **real class**;
querying a **child** filters itself:

```python
animals = session.all(SnakeQuery(Animal))
# [Dog(id=1, kind='dog', name='Toby', breed='mongrel'),
#  Cat(id=2, kind='cat', name='Fluffy', lives=9)]

dogs = session.all(SnakeQuery(Dog))  # WHERE kind = 'dog', automatic
```

The discriminator is set by the **class** (don't pass it to `__init__`):

```python
session.add(Dog(name="Toby", breed="mongrel"))  # no `kind=`
```

That's why it's declared with `snake_discriminator()` and not a decorator parameter: only a field
specifier can carry the `init=False` that mypy and pyright read. There's no `inherits=Animal`: `class
Dog(Animal)` already says it.

### Rules

!!! warning "A child's own columns have to allow `NULL`"

    The table is ONE: `Cat`'s `lives` also exists in `Dog`'s rows. A `NOT NULL` would make it
    impossible to insert a dog. It's checked when declaring the model.

!!! note "The discriminator is indexed on its own"

    Every query to a subclass carries `WHERE kind = '...'`. Without an index, each read scans the
    entire hierarchy.

!!! info "An unknown value breaks nothing"

    A row with a discriminator this process doesn't know is hydrated as the **base** class. The
    subclass fields are lost; the row is not.

### Migrations

The base creates the table, with the union of columns from the hierarchy — the union `snake_link()`
computed. The children do **not** generate their own `CREATE TABLE`. Adding a subclass is one
`AddColumn` per column it contributes.

!!! danger "`snake_link()` has to have run wherever the hierarchy is used"

    Not only before `makemigrations`. Without it the union is never folded in, and **nothing raises**:
    the `CREATE TABLE` comes out short, and a session hydrates a `Dog` whose `breed` reads `MISSING`.
    Same silence on both sides. Link where the models are imported, once, and every reader gets the
    whole hierarchy.

---

Next: [indexes and constraints](indexes-and-constraints.md).
