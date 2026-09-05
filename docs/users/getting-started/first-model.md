# Your first model

A model is a class with typed descriptors. No metaclass, no magic field.

```python
from snakeorm import SnakeColumn, SnakeModel, snake_auto, snake_column, snake_model, snake_str

@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    email: SnakeColumn[str] = snake_str(unique=True)
    nickname: SnakeColumn[str | None] = snake_str()
    active: SnakeColumn[bool] = snake_column(default=True)
```

Generates:

```sql
CREATE TABLE "public"."users" (
  "id" BIGSERIAL,
  "email" TEXT NOT NULL,
  "nickname" TEXT,
  "active" BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY ("id"),
  CONSTRAINT "uq_users_email" UNIQUE ("email")
)
```

## Three things to understand

### 1. The type is set by the annotation, and only the annotation

`nickname: SnakeColumn[str | None]` is nullable because the `| None` is there. There's no
`nullable=True`: two sources for the same piece of data means one can lie.

The rest follows. On PostgreSQL: `int` → `BIGINT`, `Decimal` → `NUMERIC`, `dict` → `JSONB`, `UUID`
→ `UUID`; and `datetime` → `TIMESTAMP` while `SnakeUtc` → `TIMESTAMPTZ`, because a wall-clock time
and an instant are two different column types and the annotation is what says which. The metadata
only adds SQL info (uniqueness, defaults), never the type.

The complete table — every type, against the three engines — is in
[columns and types](../guide/columns.md#supported-types), and only there. A table copied into a
second page is a table that goes out of sync, and this one already did.

### 2. `snake_auto()` is not a constructor argument

```python
user = User(email="ana@x.com", nickname=None)  # no `id`
```

The autoincrement PK is set by the database, so it's **excluded** from `__init__`. After the
`INSERT`, the value appears (it came in the `RETURNING`):

```python
session.add(user)
user.id  # there it is
```

### 3. It prints and compares the way you'd expect

```pycon
>>> user
User(id=7, email='ana@x.com', nickname=None, active=True)
```

Equality goes by **primary key**, not by value. Composite PKs use the same code, no special case.

!!! warning "Hashing an object without a PK raises `TypeError`"

    On purpose. If the hash came from an empty PK, the `INSERT` would fill it in afterward and mutate
    the hash of an object already inside a `set`. Insert it first.

## Table names

```text
@snake_model                                   # table: "users" (class name + s)
@snake_model(table="users_legacy")          # table: "users_legacy"
@snake_model(prefix="app", table="users")   # table: "app_users"
@snake_model(schema="analytics")               # table: "analytics"."users"
```

!!! note "Default pluralization is naive"

    `f"{ClassName.lower()}s"`. `User` → `users`, but `Country` → `countrys`. For real plurals use
    `table="..."`.

## Abstract bases

Shared columns (audit ones, typically) without the base being a table:

```python
from snakeorm import SnakeUtc, snake_abstract, snake_datetimetz

@snake_abstract
class WithAudit(SnakeModel):
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)

@snake_model(table="orders")
class Order(WithAudit):
    id: SnakeColumn[int] = snake_auto()
```

`WithAudit` contributes its columns to every child table and generates none of its own. Querying
it raises an explicit error.

For the other forms of inheritance —duplicating columns across sibling tables, or sharing a table
with a discriminator— see [inheritance](../guide/inheritance.md).

---

Next: [querying](querying.md).
