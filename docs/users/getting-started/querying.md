# Querying

`SnakeQuery(Model)` builds; `SnakeSession` executes. **Building doesn't execute**: a `SnakeQuery` is
immutable and hasn't touched the database.

```python
from snakeorm import SnakeQuery, SnakeSession, PostgresDialect, PsycopgDriver

dsn = "postgresql://user:pass@localhost/mydb"
session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())

active_users = session.all(
    SnakeQuery(User).filter(User.active == True).order_by(User.email)
)
```

Each method returns a **new** query; the previous one is untouched:

```python
base = SnakeQuery(User).filter(User.active == True)
first_page = session.all(base.limit(10))
how_many   = session.count(base)  # `base` stays intact
```

## Reading

| Call | Returns |
|---|---|
| `session.all(query)` | `list[T]` |
| `session.first(query)` | `T \| None` |
| `session.count(query)` | `int` |
| `session.exists(query)` | `bool` |

There's no `session.get(...)`. For a single row by PK, use `first()` with a filter.

## Filtering

Python operators over the **class** attributes:

```python
SnakeQuery(User).filter(
    User.email.like("%@company.com"),
    User.created_at > cutoff,  # implicit AND between arguments
)
```

Repertoire: `==`, `!=`, `<`, `<=`, `>`, `>=`, `.in_()`, `.not_in()`, `.like()`, `.ilike()`,
`.startswith()`, `.endswith()`, `.between()`, `.is_null()`, `.is_not_null()`. Combine them with `&`
(AND), `|` (OR), `~` (NOT), **always with parentheses**:

```python
SnakeQuery(User).filter((User.active == True) & ~User.nickname.is_null())
```

The right-hand side may be **another column**, and it costs no parameter — a column reference is part
of the statement, not a value travelling beside it:

```python
SnakeQuery(Stock).filter(Stock.quantity > Stock.reserved)
SnakeQuery(Stock).filter(Stock.quantity - Stock.reserved > minimum)
```

The pair stays typed: comparing an `int` column against a `str` one is rejected by the checker, which
is the mistake this is worth having. Arithmetic composes the same way and always did.

!!! danger "SQL is ALWAYS parameterized"

    Values are never interpolated: emission returns `(sql, params)` and the driver sends them
    separately. That kills SQL injection and enables multi-engine: the placeholders (`%s`, `?`,
    `$1`) are precisely what changes between engines.

### Reading inside a JSON column

```python
SnakeQuery(Doc).filter(Doc.meta.json_get("size", as_type=int) > 100)
SnakeQuery(Doc).filter(Doc.meta.json_get("owner", "name", as_type=str) == "ada")
```

`as_type` is required, and it is not ceremony. What an engine gives back from a document is TEXT, so
without a declared type that first line would be a text comparison — and as text, `'9' > '100'` is
true. The declared type is what makes the ORM emit the cast.

Several keys walk a nested path in ONE access. Each engine spells it its own way (`->>` and `#>>`,
`JSON_EXTRACT` with an unquote, `json_extract`); the dialect writes it, you do not.

!!! warning "The document is not checked by the ORM"

    If it does not hold what you declared, the ENGINE says so. SnakeORM cannot know what is inside a
    document it did not write, and guessing would be the one thing it never does.

### Bringing half a row

On a wide table, `only()` names the columns to load and `defer()` names the ones to leave. The
primary key always travels: a row with no identity cannot be written back nor matched to its
relations.

```python
session.all(SnakeQuery(Visit).only(Visit.path))     # + the primary key, always
session.all(SnakeQuery(Visit).defer(Visit.agent))   # everything except that one
```

Reading a column that was left out raises `SnakeColumnNotLoaded` — it does not come back as `None`.
That refusal is the feature: a value nobody loaded must never look like a value.

`only()` / `defer()` does NOT combine with `include()`: the pair raises `SnakeUnsupportedFeature`
instead of silently dropping the columns you named. Use `select(...)` if what you want are values.

!!! tip "Most of the time you want `select()` instead"

    If what you need are the VALUES, `session.select(query, Visit.path, Visit.ms)` gives typed
    tuples, costs no half-built instance and cannot raise later. Reach for `only()` when what you
    want IS the model — to hand it to code that expects one.

!!! warning "A partial row cannot be written back"

    `session.update(row)` on a row built by `only()`/`defer()` raises `SnakeColumnNotLoaded`: the
    UPDATE covers every non-PK column and the ones you left out are not there to send. The primary
    key travelling does not help — with PK and all, the only write that survives is
    `session.delete(row)`. And `update_where` is no way round it either, because `only()` is one of
    the knobs the bulk-write guard refuses.

    If you need to write, read the row whole, or use `select()` and then `update_where` by primary
    key.

## Navigating relationships

What sets this ORM apart:

```python
SnakeQuery(Car).filter(Car.brand.country.name == "Spain")
```

No magic strings and no hand-written `join()`: the JOINs come out of the path you navigated, each
hop checked by the type-checker.

## Bringing in the related ones

Navigating filters; to **bring in** the related objects, ask with `.include()`:

```python
cars = session.all(SnakeQuery(Car).include(Car.brand))
cars[0].brand.name  # already loaded, no second query
```

Without `include`, touching `car.brand` raises `SnakeRelationshipNotLoaded` instead of firing a query
behind your back. That avoids N+1 by default: **the ORM won't go to the database unless you ask**.

```python
session.all(SnakeQuery(Car).include(Car.brand.country))  # to-one: LEFT JOIN
session.all(SnakeQuery(Brand).include(Brand.cars))      # to-many: select-in, not a JOIN
```

The to-many select-in is sliced to fit the engine's placeholder ceiling, so a large set of parents
costs several second queries instead of one the driver would reject.

## Projecting and aggregating

When you don't want the whole object, `select()` returns **tuples**:

```python
from decimal import Decimal
from snakeorm import SnakeQuery, count, sum_

gq = SnakeQuery(Car).group_by(Car.brand_id).having(count() > 1)
rows = session.select(gq, Car.brand_id, count(), sum_(Car.price))
# list[tuple[int, int, Decimal | None]]  -> rows[0][1] is int, not Any
```

For typed objects instead of tuples, `session.annotate(query, ResultClass, **aggregates)` groups by
the base model's PK.

!!! note "`sum_`, `avg`, `min_` and `max_` return a NULLABLE type"

    Because SQL says so: over zero rows they return `NULL`, not `0`. That's why they force you to
    write `Decimal | None`. `count()` is `int`: over zero rows it returns `0`.

## Ordering, paginating, deduplicating

```python
SnakeQuery(User).order_by(User.email.desc())
SnakeQuery(User).order_by(User.nickname.asc().nulls_last())
SnakeQuery(User).limit(20).offset(40)
SnakeQuery(User).distinct()
```

!!! tip "`NULLS FIRST/LAST` isn't written unless you ask"

    Without `.nulls_first()` / `.nulls_last()` the engine's own default applies, and it is **not
    the same** across all of them. Inventing an unrequested behavior would be worse.

!!! info "MySQL and MariaDB get a different spelling, and the same rows"

    Neither has the `NULLS LAST` keyword — both answer `ERROR 1064` to it — so the ORM writes the
    portable form, `ORDER BY (nickname IS NULL) ASC, nickname ASC`. You ask the same way on the
    three engines and the rows come back in the same order; what changes is one extra sort key in
    the emitted SQL.

!!! danger "`count()` refuses `distinct()` and `group_by()`"

    Not a limitation — a refusal, and one worth understanding. `COUNT(*)` over a query that
    deduplicates or groups is a different number from the one the query would return: rows, not
    distinct rows; rows, not groups. Silently answering the first while you asked the second is the
    kind of mistake that lands in a paginator and shows the wrong number of pages for months.

    **`limit()` and `offset()` are the exception, and they ARE dropped in silence.** A `COUNT` is
    meant to answer "how many are there", so the page you asked for is deliberately ignored — which
    is what makes `session.count(base)` the right call next to `session.all(base.limit(10))`. Say it
    out loud because the corner is sharp: `session.exists(query.limit(0))` answers **True**, on a
    query that cannot return a single row.

    ```python
    users = SnakeQuery(User).distinct()
    session.all(users)               # the distinct rows
    session.count(users)             # refused: this number would not be theirs

    # Ask for the count of what you actually want counted
    distinct_emails = session.select(SnakeQuery(User).group_by(User.email), User.email)
    ```

    Same rule for `all()` with `group_by()`: a grouping only has an answer as a **projection**, so
    it goes through `select()`, which is where columns and aggregates can live together.

## Walking a lot without loading it all

`all()` builds a list with **every** row before returning the first one. Over ten million rows that's
ten million tuples and ten million objects in memory, and nobody needs to see more than one at a time
to export them.

```python
for invoice in session.iterate(SnakeQuery(Invoice), chunk=500):
    export(invoice)
```

The result stays in the engine (a server-side cursor on Postgres and MySQL) and only `chunk` rows
travel at a time. It is **lazy**: nothing runs until you ask for the first row, so breaking out early
doesn't pay for the rest. Async works the same, with `async for`.

!!! warning "It does not coexist with a to-many `include()`"

    `iterate()` **raises** if you pass a to-many `include()` or a prefetch. The select-in needs ALL
    the roots to fire its second query, and here rows come out one at a time. Serving it would mean
    materializing them (the very thing you were avoiding) or one query per row (an N+1). Both betray
    what you asked for, so it says so out loud instead of deciding for you.

    A **to-one** `include()` does work: it travels in the same JOIN, row by row.

## Writing

```python
user = User(email="ana@x.com", nickname="ana")
session.add(user)  # INSERT; fills the generated id
user.nickname = "anita"
session.update(user)  # UPDATE ... WHERE pk = ...
session.delete(user)
session.commit()
```

`commit()` closes the transaction; `rollback()`, `savepoint()` and `set_isolation()` are in
[transactions](../guide/transactions.md).

`add()` fills the generated id, but **not by the same route on every engine**. Where there is
`RETURNING` (PostgreSQL and SQLite) the INSERT brings the server-side columns back in the same round
trip. MySQL/MariaDB has no `RETURNING`: there the autoincrement id comes from `last_insert_id`, asked
of the connection right after the write. For you the outcome is identical — `user.id` has a value —
and the difference only surfaces in bulk, which is the next section.

In bulk. `update_where` takes a **sequence of pairs** `(column, value)`, not a dict:

```python
session.add_all([u1, u2, u3])
session.update_where(
    SnakeQuery(User).filter(User.active == False),
    [(User.active, True)],
)
session.delete_where(SnakeQuery(User).filter(User.created_at < cutoff))
```

!!! warning "A bulk write uses the FILTER, and nothing else"

    `update_where`/`delete_where` emit the `WHERE` and no other knob. Any other one you set on the
    same query is **refused** with `SnakeUnsupportedFeature` — `limit()`, `offset()`, `order_by()`,
    `only()`, `distinct()`, `for_update()`. It is not that they are ignored: dropping what you asked
    for would answer a different question without saying so.

    ```text
    a bulk DELETE only uses the filter (WHERE), and it does not emit limit(). Dropping what
    you asked for would answer a different question without saying so: select the rows first
    if you need those, then write by primary key.
    ```

    `limit()` is the one that hurts, because deleting in batches is exactly what somebody reaches
    for. And with **no filter at all** it is refused too: a `DELETE` with no `WHERE` would take the
    whole table.

!!! warning "Without `RETURNING`, `add_all()` does NOT fill autoincrement PKs"

    On MySQL/MariaDB the rows ARE inserted; what stays empty is the `id` **in memory**. There is
    nothing to fill it with: `last_insert_id` speaks of ONE row, and whether the ids of a multi-row
    INSERT come out consecutive depends on the server, not on the ORM. Guessing there would mean
    writing foreign keys in silence.

    So the ORM **warns** instead of forbidding, once per engine. **If you need the ids afterwards,
    use `add()` per instance.** That's the whole workaround.

!!! warning "Bulk writes do NOT fire signals"

    An `update_where` is ONE SQL statement: there are no objects to notify. If you have signals
    registered, the ORM **warns** you. See [signals and triggers](../guide/signals-and-triggers.md).

---

Next: [migrations](migrations.md), or jump to
[advanced queries](../guide/advanced-queries.md) if you're already comfortable.
