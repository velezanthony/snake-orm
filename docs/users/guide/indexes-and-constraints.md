# Indexes and constraints

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

Indexes can be declared **inside** the class body, with the `SnakeIndexes` list. CHECK constraints
and partial indexes cannot: a condition like `Person.age >= 18` needs `Person` to already exist as a
class so the descriptor returns a typed expression, so they go **outside**, with `snake_checks()` and
`snake_indexes()`.

!!! warning "A `SnakeIndex` takes COLUMNS, never their names"

    `SnakeIndex(Person.email)` outside the body, `SnakeIndex(email)` inside it — never
    `SnakeIndex("email")`. A string is not checked by anything: renaming the column would leave it
    silently pointing at a column that no longer exists.

## CHECK constraints

```python
snake_checks(
    Person,
    snake_check(Person.age >= 18, name="adult"),
    snake_check(Person.email.like("%@%")),
)
```

The condition is **the same `SnakeCondition` that `.filter()` uses**: mypy and pyright check it; if
you rename the column, it stops compiling. Without `name=`, the name is deterministic:
`ck_people_age`.

!!! warning "Two CHECKs over the same column need a `name=`"

    Deterministic means derived from the table and the column, and from nothing else, so
    `snake_check(Person.age >= 18)` and `snake_check(Person.age <= 120)` both come out
    `ck_people_age`. Declaring them raises nothing: the DDL carries the name twice and it is the
    ENGINE that stops the migration — PostgreSQL answers `check constraint "ck_people_age" already
    exists`. That is the wrong end of the pipeline to find out, so give the second one a `name=`.

!!! note "Subqueries are rejected at declaration time, not at migration time"

    An `EXISTS` or a subquery inside a CHECK can't fit in a migration file, and PostgreSQL doesn't
    allow it either. Rejecting it when you write it is correctness, not a limitation.

## Indexes

```python
snake_indexes(
    Person,
    SnakeIndex(Person.surname, Person.name),
    SnakeIndex(Person.email, unique=True),
)
```

Or the per-column shortcut, for the simple case:

```python
surname: SnakeColumn[str] = snake_str(index=True)
```

### Partial indexes

```python
snake_indexes(
    Customer,
    SnakeIndex(Customer.name, where=Customer.closed_on.is_null()),
)
```

It only indexes the active rows — on an engine that HAS partial indexes. MySQL/MariaDB has no
`WHERE` in its `CREATE INDEX`, and there the same declaration goes two different ways: a search
index is **degraded**, the `WHERE` is dropped and the index is created over the whole table (it
finds the same rows and costs more space, and the session says so once); a partial UNIQUE index
**stops the plan**, because widening it would forbid rows your domain allows, which is a different
schema and not a slower one. Both are written out in [limits](../reference/limits.md).

### Index method

```python
from snakeorm.metadata import SnakeIndexMethod

snake_indexes(Document, SnakeIndex(Document.content, method=SnakeIndexMethod.GIN))
```

`BTREE`, `HASH`, `GIN`, `GIST`, `BRIN`. The enum is one for every engine; what each engine ACCEPTS
is not, and the dialect raises `SnakeDialectError` on what it cannot translate rather than quietly
handing you an ordinary index that answers a different question:

| Engine | What it takes |
|---|---|
| PostgreSQL | every one of them |
| MySQL/MariaDB | `BTREE` and `HASH`. `GIN`, `GIST` and `BRIN` are Postgres's own and are refused |
| SQLite | `BTREE` only — it has ONE kind of index, so anything else is refused |

`BTREE` is omitted from the SQL because it's the default, and that omission is exactly what makes it
the portable one: it never reaches the dialect's translation, so a declaration with `BTREE` — or
with no `method=` — runs on the three. Anything else narrows the model to the engines that have it,
and this is the place where saying so costs one word.

## Uniqueness: constraint or index

| How you ask for it | What comes out | Name |
|---|---|---|
| `snake_column(unique=True)` | `CONSTRAINT ... UNIQUE` | `uq_table_column` |
| `SnakeIndex(..., unique=True)` | `CONSTRAINT ... UNIQUE` | `uq_table_columns` |
| `SnakeIndex(..., unique=True, where=...)` | `CREATE UNIQUE INDEX` | `ix_table_columns` |

The first two produce **the same object**: the constraint SAYS the domain rule; the index is just how
it's implemented. The third is the exception, with an engine-level reason: PostgreSQL **doesn't
allow** `UNIQUE ... WHERE`, so a partial unique can only exist as an index.

!!! info "In SQLite the constraint is translated to a unique index"

    SQLite doesn't have `ALTER TABLE ... ADD CONSTRAINT`. A `CREATE UNIQUE INDEX` gives the same
    guarantee; the name doesn't change. See [dialects](../engines/dialects.md).

## Which index is missing: `snakeorm advise`

```bash
uv run snakeorm advise --models myapp.models
```

It audits the schema and lists the foreign keys with **no index** — the most filtered and joined
columns there are — with the fix next to each one:

```text
2 FK(s) without an index (worth indexing):
  orders.customer_id  ->  snake_column(index=True)
  lines.order_id  ->  snake_column(index=True)
```

It is static: it reads the metadata, opens no connection and runs no query. The live half — which
columns the queries you actually emitted filtered on, ordered by the worst duration — is in the
[debug panel](debugging.md).

---

Next: [advanced queries](advanced-queries.md).
