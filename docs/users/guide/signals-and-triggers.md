# Signals and triggers

```python
from snakeorm import SnakeSignal, snake_on

@snake_on(Order, SnakeSignal.POST_SAVE)
def notify(order: Order) -> None:
    send_email(order.customer_email)
```

Two distinct mechanisms, in two distinct places. The rule: if it's a **data rule**, put it in a
database trigger; if it's an **application effect**, put it in a code signal.

| | Code signals | Database triggers |
|---|---|---|
| Where it runs | In your Python process | Inside the engine |
| Which writes it sees | Only ORM writes | **All of them**, from wherever they come |
| What it can do | Anything (email, enqueue a job) | Only what the database allows |
| Bulk writes | Doesn't see them | Does see them |
| Migrations | Not applicable | Versioned like any object |

## Code signals

Four moments: `PRE_SAVE`, `POST_SAVE`, `PRE_DELETE`, `POST_DELETE`. The handler receives the
**instance**, typed (example above).

!!! warning "A handler that raises takes the write with it — if there is a transaction"

    Exceptions are not caught, on purpose: swallowing them would leave half-saved data that nobody
    notices. But what UNDOES the write is the transaction, not the signal: `with SnakeSession(...)`
    rolls back on the way out. Outside one, the exception reaches you and whatever was already
    committed stays committed. The signal is the alarm; the `with` is the safety net.

!!! danger "Bulk writes do NOT fire signals"

    ```python
    session.update_where(SnakeQuery(Order).filter(Order.id > 0), [(Order.status, "closed")])
    session.delete_where(SnakeQuery(Order).filter(Order.id > 0))
    ```

    Each is ONE SQL statement: there are no instances to notify, and loading them would be N+1. Both
    `update_where` and `delete_where` **warn** you if the model has registered signals. If you need
    them, iterate with `session.update(instance)` / `session.delete(instance)`.

## Database triggers

They're declared as metadata, enter the diff, and travel in migrations just like a table:

!!! warning "Most of this section is PostgreSQL only"

    A trigger's body is engine SQL, so the ORM carries it rather than translating it. Three things
    to know before copying the example below:

    - **`snake_function` is PostgreSQL only.** `Cap.STORED_FUNCTIONS` is `Nope` on MySQL/MariaDB and
      on SQLite, so a migration that creates one is refused on both, by name.
    - **`events=[INSERT, UPDATE]` on one trigger is PostgreSQL grammar.** The emitter joins them with
      `OR`, which MySQL and SQLite reject.
    - **`TRUNCATE` with the default `for_each_row=True` is rejected by PostgreSQL itself**: a
      truncate trigger is statement-level. Pass `for_each_row=False`.


```python
from snakeorm import SnakeTriggerEvent, SnakeTriggerTiming, snake_function, snake_trigger

snake_function(
    name="stamp_modified",
    body="""
    CREATE OR REPLACE FUNCTION stamp_modified() RETURNS trigger AS $$
    BEGIN
        NEW.modified_at := now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
)

snake_trigger(
    name="tg_orders_stamp",
    table="orders",
    timing=SnakeTriggerTiming.BEFORE,
    events=[SnakeTriggerEvent.INSERT, SnakeTriggerEvent.UPDATE],
    body="EXECUTE FUNCTION stamp_modified()",
)
```

The body is **opaque**: the ORM doesn't interpret it, it just versions it and generates the migration
when it changes. There's no PL/pgSQL builder, on purpose.

Write the body with `CREATE OR REPLACE`: the ORM emits it verbatim for both creation and change, so a
bare `CREATE FUNCTION` fails the second time with *function already exists*.

The rest of the catalogue:

| Argument | Values |
|---|---|
| `timing` | `BEFORE`, `AFTER`, `INSTEAD_OF` |
| `events` | `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` |
| `for_each_row` | `True` by default (row trigger); `False` for a statement trigger |
| `schema` | `"public"` by default |

## Which one to choose

- Stamping `modified_at` → **trigger**. Applies to every write.
- Denormalized counter → **trigger**. It's a data rule.
- Welcome email → **signal**. The database doesn't send emails.
- Invalidating a cache in your app → **signal**. The database doesn't know what your cache is.
- Auditing who changed what → **trigger** if it's "everyone"; **signal** if you only care about what
  goes through the application.

---

Next: [dialects](../engines/dialects.md).
