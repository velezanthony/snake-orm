# Advanced queries

When `.filter()` falls short: expressions, windows, compound, recursive, locking, and raw SQL.

## Conditional expressions

```python
from snakeorm import snake_case, snake_coalesce, snake_nullif

tag = snake_case(
    (Order.total > 1000, "large"),
    (Order.total > 100, "medium"),
    default="small",
)
visible = snake_coalesce(User.nickname, User.email)  # the first one that is not null
safe = snake_nullif(Order.discount, 0)               # NULL when it is 0

session.select(SnakeQuery(Order), Order.id, tag, safe)
```

All three are `SnakeValue`: they compare, project, and sort like any column. They are values, not
rows, so `session.select()` is what runs them; `all()` does not take them.

## Window functions

```python
from snakeorm import dense_rank, lag, lead, rank, row_number, sum_

position = row_number().over(
    partition_by=[Sale.region],
    order_by=[Sale.amount.desc()],
)
previous = lag(Sale.amount)
running = sum_(Sale.amount).over(order_by=[Sale.sold_on.asc()])

session.select(SnakeQuery(Sale), Sale.region, position, running)
```

| Function | Returns | Ties |
|---|---|---|
| `row_number()` | `int` | No ties: 1, 2, 3, 4 |
| `rank()` | `int` | Ties with gaps: 1, 2, 2, 4 |
| `dense_rank()` | `int` | Ties without gaps: 1, 2, 2, 3 |
| `lag(v, n)` / `lead(v, n)` | `T \| None` | Optional: in the first `n` rows there is no previous row |

## Compound: UNION, INTERSECT, EXCEPT

```python
active = SnakeQuery(User).filter(User.active == True)
recent = SnakeQuery(User).filter(User.created_at > cutoff)

session.all(active.union(recent))      # no duplicates
session.all(active.union_all(recent))  # duplicates kept, and cheaper for it
session.all(active.intersect(recent))
session.all(active.except_(recent))
```

!!! danger "The branches must be from the SAME model"

    Mixing different models would hydrate rows into the wrong attributes with not a single error. The
    ORM rejects it at runtime.

!!! note "On SQLite a branch carries nothing of its own"

    SQLite rejects parentheses around the branches, and without them a branch's `limit()`, `offset()`
    or `order_by()` would apply to the whole set instead. The dialect declares that, and the emission
    raises `SnakeEmitError` rather than answering a different question. Order and bound the result,
    not the branch.

!!! danger "On SQLite a branch may not be a set ITSELF, unless you chain to the left"

    `a.union(b.except_(c))` puts a whole set in the right-hand branch. Without the parentheses SQLite
    reads the operators left to right, so that becomes `(a UNION b) EXCEPT c`: valid SQL, different
    rows, no error. Measured over the whole 4x4 operator matrix, 12 of the 16 pairs answered one set
    on Postgres and MySQL and another on SQLite. It is refused now. Chaining to the LEFT —
    `a.union(b).except_(c)` — is what the bare text already means and runs the same everywhere.

!!! note "A `recursive()` is a branch on Postgres only"

    `(SELECT ...) UNION (WITH RECURSIVE ...)` is Postgres. SQLite answers `near "WITH": syntax error`
    and MySQL error 1064, so both declare `Cap.CTE_IN_COMPOUND_BRANCH` as absent and the emission
    refuses instead of letting the driver complain about SQL you never wrote. Run the recursion as
    its own query and combine the rows afterwards.

## Recursive (`WITH RECURSIVE`)

For trees and graphs:

```python
# every descendant of category 1, at any depth
descendants = SnakeQuery(Category).filter(Category.id == 1).recursive(
    on=(Category.parent_id, Category.id)
)
session.all(descendants)

# a graph that may bite its own tail: UNION instead of UNION ALL, and the walk stops on its own
reachable = SnakeQuery(Node).filter(Node.id == 20).recursive(
    on=(Node.parent_id, Node.id), distinct=True
)
```

The query is the **anchor** (where it starts) and `on` is the pair of columns that chains each level
to the previous one.

`distinct` picks the set operator that joins each step to what has already been accumulated — the
same choice `union()` and `union_all()` hand you elsewhere:

| `distinct` | operator | when |
| --- | --- | --- |
| `False` (default) | `UNION ALL` | a **tree**: it has no duplicates to drop, and dropping them would mean hashing everything accumulated on every step |
| `True` | `UNION` | a **graph** that may have cycles: the lap that repeats contributes nothing, so the step comes back empty and the walk ends |

!!! danger "`limit()` is not the way out of a cycle"

    With `UNION ALL` a cyclic walk never ends: every lap yields rows the engine counts as new, the
    step never comes back empty, and the query hangs instead of failing. A `limit()` bounds what
    comes BACK, not how far the engine goes — measured against Postgres over a three-row cycle, the
    same walk with `order_by()` and `LIMIT 3` never returns, because the sort has to produce every
    row before it can emit one.

    The ORM cannot make the call for you: a foreign key onto its own table admits a cycle perfectly
    well, so whether one exists is a fact about your domain, not about your schema. If you cannot
    rule them out, pass `distinct=True`.

!!! danger "An anchor carries no `include()`, and on SQLite no `limit()` of its own"

    A query with `include(...)` is refused as the anchor of a `recursive()` and as a branch of a
    `union`/`except_`/`intersect` — the same two places, for a reason of its own rather than the
    lock's. The columns of a CTE are the table's and the columns of a set are the projection's, so
    the relationship brought in by the LEFT JOIN has nowhere to travel: it would come back
    unloaded, quietly. Recurse or compose WITHOUT `include()` and load the relationships over the
    rows you get back.

    A `limit()` or an `offset()` on the anchor is Postgres and MySQL only. SQLite rejects the
    parentheses around the anchor, and without them the bound would read off the whole traversal
    instead of the first step, so the emission refuses it there. Bound the RESULT with `.limit()`
    on the recursion instead, which asks the same thing everywhere.

## Row locking

```python
SnakeQuery(Account).filter(Account.id == 7).for_update()
SnakeQuery(Account).for_update(nowait=True)       # fails instead of waiting
SnakeQuery(Account).for_update(skip_locked=True)  # skips the locked ones
```

With [isolation levels](transactions.md) they are the two halves of concurrency control. On an engine
without row locking (SQLite) the ORM says so; it doesn't ignore it.

!!! danger "A lock does not travel with `include()`"

    `for_update()` beside `include()` is refused, out loud. The two ask for different SQL — the lock
    is over the rows of ONE table and `include()` brings in another by LEFT JOIN — and locking every
    joined table is almost never what somebody meant. Lock first, then load:

    ```python
    # First the lock, on its own query and nothing else
    account = session.first(SnakeQuery(Account).filter(Account.id == 7).for_update())

    # Then whatever you need loaded, in a second query WITHOUT the lock
    detail = session.first(SnakeQuery(Account).filter(Account.id == 7).include(Account.owner))
    ```

    The same refusal covers `union`/`except_`/`intersect` and the anchor of a `recursive()`: a set
    has no rows of a specific table to lock.

## Raw SQL

The escape hatch, for when the builder falls short:

```python
from decimal import Decimal

from snakeorm import SnakeRow, snake_row

@snake_row
class Summary(SnakeRow):
    region: str
    total: Decimal

rows = session.raw(
    "SELECT region, SUM(amount) AS total FROM sales WHERE sold_on > %s GROUP BY region",
    (cutoff,),
    into=Summary,
)
rows[0].total  # Decimal, typed
```

Still **parameterized**: the values travel separately, never inside the string. The placeholder is
yours to write and it depends on the engine — `%s` on PostgreSQL and MySQL, `?` on SQLite — because
`raw()` hands the string to the driver untouched.

## Procedures and functions

```python
session.call("compute_totals", [2024], into=Summary)     # returns rows
session.execute_procedure("recalculate_everything", [])  # returns nothing
```

`call()` emits `SELECT * FROM name(...)` and hydrates the rows positionally into the `@snake_row`
you declare; `execute_procedure()` emits `CALL name(...)` and returns nothing. The args travel
parametrised, as everywhere else; the name is an identifier, so it cannot, and it goes through a
check on its shape instead.

This is **opaque SQL**, and that reaches further than the routine: nothing here asks the capability
catalogue anything, so neither the routine's existence, nor its shape against your `@snake_row`, nor
the engine's having routines AT ALL is checked. On SQLite there are none to call — its functions are
registered by the process that opens the connection, so they never live in the database — and what
comes back is the driver complaining about SQL you did not write: `no such table: compute_totals`
for `call()`, `near "CALL": syntax error` for `execute_procedure()`. Everywhere else the ORM stops
the plan before the engine sees it; the escape hatch is the one place where the string is yours and
so is the error.

## Scalar subqueries

A one-column subquery, to be used inside `.in_(...)`:

```python
recent_buyers = (
    SnakeQuery(Order)
    .filter(Order.date_ > cutoff)
    .as_scalar(Order.customer_id)
)

SnakeQuery(Customer).filter(Customer.id.in_(recent_buyers))
```

Only there: the result is not a comparable value, and it carries neither `order_by()` nor `limit()`.
A direct column and a flat `WHERE`; navigating a relationship inside it is refused in plain words.

It carries nothing of the query it WRAPS either, and that part is silent: `as_scalar()` keeps the
table, the column and the `WHERE`, so an `order_by()`, a `limit()`, an `offset()` or a `distinct()`
on the wrapped query is dropped and the SQL comes out exactly as if you had never written them.

For `order_by()` and `distinct()` that is honest: a set is the same set ordered or not, and `IN` asks
about a set. For `limit()` and `offset()` it is not — a page of rows is a different question from all
of them, and here that question disappears instead of being refused. When you want the top rows, run
that query, take the values, and filter by them.

## Composite IN

Filtering by a TUPLE of columns, which is `(warehouse_id, product_id) IN ((7, 3), (9, 1))` in SQL:

```python
snake_keys(Stock).in_([
    snake_key(Stock).set(Stock.warehouse_id, 7).set(Stock.product_id, 3),
    snake_key(Stock).set(Stock.warehouse_id, 9).set(Stock.product_id, 1),
])
```

One `in_()` per column is a DIFFERENT question:
`Stock.warehouse_id.in_([7, 9]) & Stock.product_id.in_([3, 1])` is the cartesian product, and it
also answers `(7, 1)` and `(9, 3)`. With few rows the two look alike.

Each column is paired with its own value instead of being positional, and that is what makes the
type checker useful here: the slot binds the type, so a value of the wrong type is refused at the
column it was set against. A positional tuple of two integers gives the checker nothing to line up,
so a swapped pair type-checks and comes back wrong. There is also no arity limit — no overloads are
involved, so a key six columns wide is written the same way as one of two.

The slot takes any scalar expression, not only a bare column, and the columns need not be a key:

```python
from snakeorm.expressions import snake_upper

snake_keys(Stock).in_([
    snake_key(Stock).set(snake_upper(Stock.city), "BILBAO").set(Stock.units, 4),
])
```

That import is written out because it is the one a reader would get wrong: `snake_key`,
`snake_keys`, `snake_case` and `snake_coalesce` are re-exported by the root package, and the string
functions — `snake_upper`, `snake_lower`, `snake_concat` — are not.
`from snakeorm import snake_upper` is an `ImportError`.

The chaining order is yours; the emitted column list follows the model's declaration order, so two
keys chained differently produce the same SQL.

What the type system cannot check is how many slots a key has — a two-column key and a three-column
one are both `SnakeKey[Stock]` — so those failures raise before anything is emitted: an empty key,
the same column set twice, and keys of the same list that do not present the same columns. That last
one is the quiet failure: two keys of equal width over different columns would compare each row's
values against the first row's columns, and two integers never make an engine complain.

Every engine runs this, and all three run it AS a row constructor: `(a, b) IN ((...), (...))`, with
nothing changing but the quoting and the placeholder. The ORM keeps an equivalent
`(a = ? AND b = ?) OR (...)` for a dialect that declares no `Cap.ROW_CONSTRUCTOR`, and it asks the
same question — but every dialect here declares it `Full()`, so that fallback is a door none of the
supported engines walks through.

There is a ceiling, and it is the engine's: see [limits](../reference/limits.md).

---

Next: [transactions](transactions.md).
