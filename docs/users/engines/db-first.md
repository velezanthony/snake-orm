# DB-first and scaffolding

The scaffolder **translates a live database into models**. Point it at any schema — one a DBA
governs, one that belongs to another repository, one a serverless function has to talk to — and what
comes out queries through the same typed API as a hand-written model, under Django, FastAPI or
Flask, or under plain Python with no framework at all. Nothing to wire up: connect, generate, query.

```bash
uv run snakeorm scaffold create --out app/models_legacy.py --schema public
uv run snakeorm scaffold update --out app/models_legacy.py     # rewrites it whole
```

- `create` fails if the file already exists.
- `update` **overwrites it entirely**: it's a mirror of the database, it doesn't keep your edits.

## What it generates

```python
from __future__ import annotations

from snakeorm import (
    SnakeColumn, SnakeIndex, SnakeModel, SnakeToMany, SnakeToOne,
    snake_auto, snake_db_first, snake_int, snake_link, snake_str,
    snake_to_many, snake_to_one,
)

@snake_db_first(table="countries")
class PublicCountries(SnakeModel):
    """Mirror of table `countries`."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    customers_legacy: SnakeToMany[PublicCustomersLegacy] = snake_to_many("country")


@snake_db_first(table="customers_legacy")
class PublicCustomersLegacy(SnakeModel):
    """Mirror of table `customers_legacy`."""

    SnakeComment = "Customers imported from the 2011 system"

    id: SnakeColumn[int] = snake_auto()
    razon_social: SnakeColumn[str] = snake_str()
    nif: SnakeColumn[str | None] = snake_str(unique=True)
    country_id: SnakeColumn[int] = snake_int()
    country: SnakeToOne[PublicCountries] = snake_to_one(country_id)

    SnakeIndexes = [
        SnakeIndex(country_id),
    ]

snake_link()
```

A `@snake_db_first` is a **complete** model: it queries, inserts, updates and deletes like any other.
The only difference: **migrations ignore it** — the source of truth for its schema is the database,
not the code.

**Foreign keys come across too**, and the relationship is named after the local COLUMN with its
`_id` removed —`country_id` becomes `country`— which is the convention a hand-written model keeps.
A composite key takes the prefix its columns share. Where there is a relation to link, the file ends
in `snake_link()`; where the schema holds no foreign key at all, neither the call nor its import
appear, because there would be nothing for it to resolve. The compiler is two-phase, and a mirror
that declares relations without linking them imports cleanly and fails at the first query.

**The relationship says what its key says about NULL.** A nullable foreign key comes out as
`SnakeToOne[X | None]` and a `NOT NULL` one does not, because the linker demands that parity in both
directions — with a nullable key `include()` finds no partner and hangs a `None` off the
relationship, so a non-optional type would be a lie the checker approves.

**The reverse side is generated too**, and the collection is named after the CHILD TABLE, as it
stands: `customers_legacy` on `PublicCountries`. That transcribes a token the database already
holds instead of inventing one, which is the whole difference from a pluraliser — `status` →
`Statu` is a wrong name that compiles and that nothing detects. Where a person would have written
`customers`, the mirror gives you `customers_legacy`: unabbreviated, not wrong.

The rule is TOTAL, so its only failures are collisions, and every one of them is reported instead of
emitted: a name already taken by a column or by a to-one, and the one that has no answer — two
foreign keys of the same child pointing at the same parent, where nothing in the database says which
collection is `sent` and which is `received`.

## There is no in-place adoption

Swapping the decorator does **not** hand the controls to the migrations, and this page used to say
it did:

```python
# This does NOT work against the database the mirror came from:
@snake_model(table="customers_legacy")   # was: @snake_db_first
class PublicCustomersLegacy(SnakeModel):
    ...
# makemigrations emits CreateTable -> DuplicateTable, because the history never knew the table.
```

The migration history has no record of that table, so the autogen has nothing to compare against and
emits a `CreateTable` — which dies against a table that is already there. There is no `--fake` and no
baseline row to insert: this ORM does not offer one.

**What the mirror IS for** is taking a schema to ANOTHER database, governed from scratch. Strip the
decorator there, and the `CreateTable` the autogen emits is exactly right. The original database is
left untouched, which is the point: db-first means the schema belongs to the sysadmin and this ORM
is a customer.

!!! info "An FK toward a mirror model IS emitted"

    If a managed model points to an unmanaged one in the **same** database, the constraint is
    created: the table exists, you just didn't create it. Across different databases the guard from
    [multiple databases](multi-connection.md) applies.

## Class names

The class is named after the **table**, in CapWords, with the **schema in front** —`public` included:

| table | class |
|---|---|
| `public.project_requests` | `PublicProjectRequests` |
| `sales.orders` | `SalesOrders` |
| `public.ProductReQuests` | `PublicProductReQuests` |

**The plural is left alone**, and that is the decision that matters. Removing a trailing `s` guesses
at English: it turns `status` into `Statu`, `analysis` into `Analysi` and `direcciones` into
`Direccione`, and it is right in Spanish only by accident. Splitting on `_` and capitalising knows no
language and loses nothing, so that half stays.

**The schema has no carve-out.** `sales.orders` beside `hr.orders` is ordinary, and without the
prefix they are one class — the mirror would keep whichever came last and say nothing.

Two flags turn each half off:

```bash
snakeorm scaffold create --out models.py --keep-underscores   # Public_project_requests
snakeorm scaffold create --out models.py --no-schema-prefix   # ProjectRequests
```

Dropping the prefix does not hide what it was preventing: the tables that then collapse onto one
class are reported by name.

**What cannot be named is never invented.** A table or column whose name is not an ASCII identifier —
accents, another alphabet, a Python keyword — is left out and reported, in the file and on the
console. A guessed name is a mirror pointing at something nobody asked for.

## What a mirror cannot carry

A database is a **lossy projection of code**. The scaffolder can only give back what the catalogue
holds, and everything below lives in a `.py` — often in another repository — with no row of any
system table mentioning it. It is not that the generator does not do it yet: there is nowhere to
read it from.

| what | what the database stores | what is lost |
|---|---|---|
| `snake_on` / signals | nothing | the handler — it is a Python function |
| `snake_enum` | the labels | the `StrEnum` class, its member NAMES, its methods |
| `default_factory=` | nothing | `datetime.now`, `uuid4`: computed on the client, never reaches the DDL |
| domain constants | nothing | they live in a module, not in a table |
| methods, properties, docstrings | nothing | the half of a model that is not a column |
| the name a person chose | the TABLE name | `User.sessions` for `login_sessions` is a human abbreviation |
| `snake_discriminator` | an ordinary column | that THAT column marks a subtype |
| `snake_trigger` / `snake_function` | the body, in PL/pgSQL | nothing that fits in a `.py` without copying another language |

`default=` DOES come back, and the line falls exactly there: `default=` is a **DDL literal**, so the
server stores it, while `default_factory=` is a program.

Said plainly: **you cannot throw your hand-written models away, regenerate them from the mirror and
carry on.** The mirror runs the other direction — at a database you did not write.

## The round-trip is NOT bijective

`TEXT`, `VARCHAR(50)` and `CHAR(10)` all come back as `str`. A code → database → code trip doesn't
reproduce your original file. That's **correct**: the SQL→Python mapping loses information by
definition. In SQLite it's even more pronounced — its type system is affinities, not types.

## Nothing is dropped silently

Whatever the database has and the ORM can't express —triggers, exotic types, expression indexes—
comes out as a **console warning and a comment in the generated file**:

```python
# INTROSPECTION WARNINGS: this EXISTS in the database and the model does NOT
# represent it. It is still there and still acting; it just cannot be seen from here.
#   - trigger: tg_customers_audit on customers
#   - expression index: ix_customers_lower_tax_id
```

## Drift detection

```bash
uv run snakeorm check --database default
```

It compares the **real** schema against your models and warns if they don't match. It's not the same
as `makemigrations --check`:

| Command | Compares | Catches |
|---|---|---|
| `makemigrations --check` | Code ↔ **history** | "I forgot to generate the migration" |
| `check` | Code ↔ **real database** | "Someone touched the database by hand" |

You need both. With a `@snake_db_first`, `check` does look at it: your mirror may have gone stale.

---

Next: [how typing works](../reference/typing.md).
