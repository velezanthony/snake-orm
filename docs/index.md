---
hide:
  - navigation
---

# SnakeORM

**Fully typed deep relationship navigation in Python. No codegen. No type-checker plugin.**

```python
Truck.maker.nation.name == "España"  # SnakeExpr[str] -> SnakeCondition
```

Mypy, Pyright and Pylance all know it. And it generates this:

```sql
SELECT t0."id", t0."model", t0."maker_id" FROM "public"."trucks" AS t0
JOIN "public"."makers" AS t1  ON t0."maker_id" = t1."id"
JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"
WHERE t2."name" = %s
```

In Django you'd write `filter(maker__nation__name="España")`: a magic string that doesn't
autocomplete, isn't checked, and if you rename `nation` you find out in production.

The distribution is `snake-orm` and the package is `snakeorm`. The version is pinned because it is
a beta: a plain `pip install snake-orm` does not pick up a preliminary.

```bash
pip install snake-orm==0.1.0b1   # or: pip install --pre snake-orm
```

[Get started in five minutes](users/getting-started/installation.md){ .md-button .md-button--primary }
[How the typing works](users/reference/typing.md){ .md-button }

---

## A full glance

```python
from snakeorm import (
    SnakeColumn, SnakeModel, SnakeQuery, SnakeSession, SnakeToOne,
    PostgresDialect, PsycopgDriver,
    snake_auto, snake_int, snake_link, snake_model, snake_str, snake_to_one,
)

@snake_model(table="brands")
class Brand(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)

@snake_model(table="cars")
class Car(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    model: SnakeColumn[str] = snake_str()
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[Brand] = snake_to_one(brand_id)

snake_link()

session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
cars = session.all(
    SnakeQuery(Car).filter(Car.brand.name == "Seat").order_by(Car.model)
)
```

---

## The thesis

A modern ORM **can** have fully typed deep relationship navigation, without generating code and
without a type-checker plugin. **The type system is the single source of truth**; the runtime just
executes SQL over already-compiled metadata. Verified with mypy **and** pyright: a test requires
they agree — [how it works](users/reference/typing.md).

---

## What's inside

<div class="grid cards" markdown>

-   :material-key-variant:{ .lg .middle } **Typing that doesn't lie**

    ---

    Deep relationships, aggregates, projections and enums return their real type. Zero `Any`,
    verified with `--strict`.

    [:octicons-arrow-right-24: How it works](users/reference/typing.md)

-   :material-database-sync:{ .lg .middle } **Migrations with autogen**

    ---

    Diff the model against history, readable and reversible files, squash and drift detection
    against the real database.

    [:octicons-arrow-right-24: Migrations](users/getting-started/migrations.md)

-   :material-swap-horizontal:{ .lg .middle } **Three engines, one metadata**

    ---

    PostgreSQL, MySQL/MariaDB and SQLite. The model is 100% agnostic: the engine only enters when
    emitting and executing.

    [:octicons-arrow-right-24: Dialects](users/engines/dialects.md)

-   :material-lightning-bolt:{ .lg .middle } **Synchronous and asynchronous**

    ---

    SQL generation has no color, so `AsyncSession` reuses the entire core. Parity checked by the
    machine.

    [:octicons-arrow-right-24: Asynchronous](users/engines/async.md)

</div>

---

## Principles

- **Nothing fails silently.** When something can't be done, it says so; when it can be translated,
  it's translated; when the tool can't decide, it stops and asks.
- **The type comes from Python.** `SnakeColumn[str | None]` is nullable because the annotation says
  so, not a `nullable=True` that could contradict it.
- **Every limit is written down.** The [known limits](users/reference/limits.md) page is part of the
  contract, not a list of apologies.
