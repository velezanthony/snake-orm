# Transactions

```python
with SnakeSession(driver, dialect) as session:
    session.add(order)
    session.add(line)
    # commit on exit; rollback if anything raises
```

Or by hand, when you control the cycle yourself:

```python
session.add(order)
session.commit()
# session.rollback()
```

Every method the session offers is in [Sessions](../reference/api/session.md).

## Savepoints

To undo **part** of a transaction without losing the rest:

```python
with SnakeSession(driver, dialect) as session:
    session.add(order)

    try:
        with session.savepoint():
            session.add(doubtful_line)  # if this blows up...
    except SnakeError:
        pass  # ...the order stays alive

    session.commit()
```

They nest, and the session generates the names (`sp1`, `sp2`...).

## Isolation levels

```python
from snakeorm import SnakeIsolation

session.set_isolation(SnakeIsolation.SERIALIZABLE)
```

`READ_UNCOMMITTED`, `READ_COMMITTED`, `REPEATABLE_READ`, `SERIALIZABLE`. With
[`for_update()`](advanced-queries.md#row-locking) they are the two halves of concurrency control.

Two conditions the engines impose: **call it before reading or writing** (`SET TRANSACTION` is only
valid as the first statement), and **not on SQLite**, which has no isolation levels. There the call
is refused with a `SnakeUnsupportedFeature` that says why: SQLite has no
`SET TRANSACTION ISOLATION LEVEL`, one writer at a time makes its transactions serialisable already,
and its only knob —`PRAGMA read_uncommitted`— LOWERS the isolation instead of raising it.

## Retrying a serialization conflict

With `SERIALIZABLE`, the engine aborts what it can't serialize. The correct response is to **redo the
entire unit of work**:

```python
from snakeorm import with_retry

seat = with_retry(session, lambda s: reserve_seat(s, course_id))
```

`attempts=3` by default.

!!! info "Why it takes a function, not a statement"

    When the engine aborts a transaction, the **whole** thing becomes unusable (*current transaction
    is aborted*). Retrying the statement fixes nothing: you have to go back to the start with its
    `rollback` in between. That's why `with_retry` takes the complete unit of work.

    It recognises the transient conflict on all three engines. Anything else is raised straight away
    — repeating a constraint violation repeats the failure, and could duplicate side effects.

## Writes that report what happened

```python
user, created = session.get_or_create(
    SnakeQuery(User).filter(User.email == "ana@x.com"),
    lambda: User(email="ana@x.com", nickname="ana"),
)
if created:
    send_welcome(user)
```

`upsert` writes, but doesn't tell you whether it created or the row already existed:

```python
session.upsert(
    user,
    on_conflict=[User.email],
    update=[User.nickname],
)
```

## Reloading from the database

After a trigger or a server default that changed the row underneath you:

```python
session.refresh(order)
```

## In production: wrapping the driver

```python
from snakeorm import LoggingDriver, PostgresDialect, PsycopgDriver, TimeoutDriver

dialect = PostgresDialect()

driver = PsycopgDriver.connect(dsn)
driver = LoggingDriver(driver, write=print)  # write(line: str)
driver = TimeoutDriver(driver, dialect, statement_timeout_ms=5000)
```

The order matters: the logger goes first so it also records what the wrappers above it do.
`TimeoutDriver` takes the dialect because the timeout statement is the engine's — and on an engine
that has none (SQLite) it **refuses the wrap** instead of pretending to cap.

### The values do not go in the log

`LoggingDriver` writes the statement and the NUMBER of parameters, never the parameters themselves:

```
INSERT INTO users (email, pw) VALUES (%s, %s) -- params=<2 hidden> -> 1 row(s)
```

`write=print` sends that to the process stdout, which in a container is the log aggregator. The
statement is safe by construction — the ORM never interpolates, so nothing of the user's is in it —
and the values are the only thing that could be. To see one, name its position (0-based):

```python
driver = LoggingDriver(driver, write=print, parameter_keys=frozenset({"0"}))
```

There is **no environment variable** for this, and the omission is the decision: an environment
variable is precisely the switch somebody flips in production by accident. It is the same policy,
spelled the same way, as the `otel` exporter's `parameter_keys`.

For pooling, see [multiple connections](../engines/multi-connection.md).

---

Next: [signals and triggers](signals-and-triggers.md).
