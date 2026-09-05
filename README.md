# 🐍 SnakeORM

[![CI](https://github.com/velezanthony/snake-orm/actions/workflows/ci.yml/badge.svg)](https://github.com/velezanthony/snake-orm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/snake-orm?label=PyPI&color=3775A9)](https://pypi.org/project/snake-orm/)
[![TestPyPI](https://img.shields.io/pypi/v/snake-orm?pypiBaseUrl=https%3A%2F%2Ftest.pypi.org&label=TestPyPI&color=8A8A8A)](https://test.pypi.org/project/snake-orm/)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
![Engines](https://img.shields.io/badge/engines-PostgreSQL%20%7C%20MySQL%20%7C%20SQLite-336791)
![Typing](https://img.shields.io/badge/typing-mypy%20%2B%20pyright-2ea44f)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Fully typed deep relationship navigation in Python. No codegen. No type-checker plugin.**

Docs (English and Spanish): <https://velezanthony.github.io/snake-orm/>

```python
Truck.maker.nation.name == "España"   # SnakeExpr[str] -> SnakeCondition
```

```sql
SELECT t0."id", t0."model", t0."maker_id" FROM "public"."trucks" AS t0
JOIN "public"."makers" AS t1  ON t0."maker_id" = t1."id"
JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"
WHERE t2."name" = %s
```

Mypy checks it. Pyright checks it. Pylance autocompletes it. The Django equivalent,
`filter(maker__nation__name="España")`, is a string: no autocomplete, no check, and renaming
`nation` fails in production.

---

## Install

Requires Python 3.11+. SQLite ships with the standard library, so nothing needs to be running to
start.

```bash
pip install --pre snake-orm
```

The distribution is `snake-orm` and the package is `snakeorm`: `import snakeorm`. It is published
at [pypi.org/project/snake-orm](https://pypi.org/project/snake-orm/), and every release lands on
[test.pypi.org/project/snake-orm](https://test.pypi.org/project/snake-orm/) first — the same
artifact, uploaded there before the real index, because a version accepted on PyPI is spent and
cannot be replaced.

The version is a **beta**, and `--pre` is the point: a preliminary is not picked up by a plain
`pip install snake-orm`, so nobody upgrades into it by accident while the API is still moving. It
is not pinned to a number here on purpose — six pages carried that number and four of them were
already a release behind, recommending the version the newest one exists to fix.

From a checkout, to work on the ORM itself:

```bash
uv sync --all-extras --all-groups
uv run pytest          # suite
uv run mypy .          # must pass
uv run ruff check .    # must pass
```

[Installation](docs/users/getting-started/installation.md) →
[first model](docs/users/getting-started/first-model.md) →
[migrations](docs/users/getting-started/migrations.md).

```python
@snake_model(table="makers")
class Maker(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)
    nation_id: SnakeColumn[int] = snake_int()
    nation: SnakeToOne[Nation] = snake_to_one(nation_id)
    trucks: SnakeToMany[Truck] = snake_to_many("maker")

snake_link()   # once, after importing every model
```

The type always comes from the annotation. `snake_column()` only adds SQL information.

```bash
uv run snakeorm makemigrations --models myapp.models --name initial
uv run snakeorm migrate --models myapp.models --dsn "host=... dbname=..."
uv run snakeorm rollback --models myapp.models --dsn "..."
```

---

## The mechanism

**Recursive descriptors** whose `__get__` returns a different type depending on the access:

```python
user.car.name               # instance -> the value           -> str
User.car.brand.name == "x"  # class    -> a SQL expression     -> SnakeCondition
```

`User.car` returns `type[Car]`, so `.brand.name` re-triggers the class overload of `Car`'s
descriptors. `@dataclass_transform` on the decorator types `__init__`. It is the manual equivalent
of TypeScript's mapped types.

The type system is the single source of truth: the class is compiled **once** into an immutable
metadata graph, and the runtime never reflects on it again.

---

## Why Django returns `Any`

```python
User.objects.annotate(num_posts=Count("posts"))
user.num_posts   # -> Any
```

`annotate` returns "a `User` **plus** a `num_posts: int`". That is an intersection type. TypeScript
has it; Python does not. So there are three paths, and only three:

| Path | Dynamic names | Real typing | IntelliSense |
|---|---|---|---|
| `__getattr__ -> Any` | ✅ | ❌ | ❌ |
| Declared names | ❌ | ✅ | ✅ |
| Type-checker plugin | ✅ | ✅ | partial |

Django took the first and patched it with the third (`django-stubs`). SnakeORM forbids the third by
thesis and takes the second, with a typed escape hatch.

`Any` is not typing, it is switching the checker off:

```python
def __getattr__(self, name: str) -> Any: ...
u.agg.count_children * 2           # mypy: 0 errors
other: str = u.agg.count_children  # mypy: 0 errors  <- same value, as a str
```

`object` keeps the dynamic name and wakes the checker up:

```python
def __getattr__(self, name: str) -> object: ...
u.agg.count_children * 2           # error: unsupported operand types for *
count: int = cast("int", u.agg.count_children)   # explicit, and signed with your name
```

---

## Illegal states you cannot write

```python
SnakeQuery(Nation).filter(Nation.makers.name == "SEAT")
# error: "SnakeCollection[Maker]" has no attribute "name"  [attr-defined]
```

In Django that compiles, runs and silently duplicates rows — which is what `.distinct()` is for. A
to-many exposes **collection operations**, not the child's columns:

```python
q.filter(Nation.makers.any(Maker.name == "SEAT"))  # any?   -> correlated EXISTS
q.filter(~Nation.makers.any())                     # none?  -> NOT EXISTS
q.filter(Nation.makers.count() > 3)                # how many? -> scalar subquery
q.include(Nation.makers)                           # load them -> select-in, 2 queries

q.include(SnakePrefetch(Nation.makers).then(Maker.trucks))
# one query per LEVEL (root + makers + trucks = 3), never one per parent
```

One row per parent. `DISTINCT` is never needed.

```sql
-- Nation.makers.any(Maker.trucks.any(Truck.model == "Ibiza"))
SELECT "id", "name" FROM "public"."nations" WHERE EXISTS (
  SELECT 1 FROM "public"."makers" AS e0 WHERE e0."nation_id" = "nations"."id" AND EXISTS (
    SELECT 1 FROM "public"."trucks" AS e1 WHERE e1."maker_id" = e0."id" AND e1."model" = %s))
```

> **Implicit when the answer is unique. Explicit when there is more than one correct answer.**

A to-one never changes the row count, so the `JOIN` is inferred. A to-many does, so the ORM does not
guess.

---

## What the thesis gives for free

**No silent N+1.** An unloaded relation raises instead of querying:

```python
truck.maker
# SnakeRelationshipNotLoaded: Relation 'maker' was not loaded.
#                             Use .include(Truck.maker) in the query.
```

**No `F()`.** Class access already is an expression:

```python
session.update_where(query, [(Counter.views, Counter.views + 1)])
# UPDATE "counters" SET "views" = ("views" + %s) WHERE ...
```

Pairs, not a dict: `SnakeExpr` is unhashable because its `__eq__` returns a `SnakeCondition`.

**Many-to-many crosses a real model**, never an implicit table:

```python
tags: SnakeToMany["Tag"] = snake_to_many_through(through="PostTag", via="post", to="tag")
```

The bridge is an ordinary model, so extra columns on it are ordinary fields from day one.

**A bulk `UPDATE`/`DELETE` uses the filter and nothing else.** With no `WHERE` it is refused, and
so is any other knob you set on the same query — `limit()`, `order_by()`, `only()`. Dropping what
you asked for would answer a different question without saying so: select the rows first, then
write by primary key.

**`annotate()` counts with a correlated subquery, not a `LEFT JOIN`** — a parent with no children
comes out `0` instead of disappearing.

**A view is a read-only model, and navigable.** `@snake_view` maps a `VIEW` with typed columns,
navigable both ways; `session.add/update/delete` reject it in the **type**, because writing requires
a `SnakeModel`. `CreateView`/`AlterView`/`DropView` live in the migrations.

**Migration history is `.py`**, because `python_type` is a Python `type`. JSON would need a
name↔type registry: a second type system, parallel to Python's and worse.

---

## Typed annotations

Declare the result class — you choose the name, Python chooses the type:

```python
@snake_result
class RealmStats(SnakeResult[Realm]):
    realm: Realm
    forge_count: int

rows = session.annotate(query, RealmStats, forge_count=Realm.forges.count())
rows[0].forge_count  # int, with IntelliSense
rows[0].realm.name   # str, navigation intact
```

For genuinely dynamic names, the escape hatch is explicit:

```python
count = cast("int", realm.aggregate.forge_count)   # object -> the cast is mandatory
```

Without the cast it does not compile. Without annotating, it raises `SnakeAggregateNotLoaded` naming
the aggregates it does have.

---

## What is inside

| | |
|---|---|
| **Queries** | filter · order/limit/offset · group by/having · aggregates · `annotate` · explicit joins · `include` (to-one and to-many) · deep navigation · `.any()` · correlated subqueries · composite `IN` · `only`/`defer` · `iterate` (server cursor) · `for_update` · `raw` |
| **SQL** | window functions with frame · `UNION`/`INTERSECT`/`EXCEPT` · `WITH RECURSIVE` · `CASE`/`COALESCE`/`NULLIF` · text, date and math functions · `json_get` · `ILIKE` |
| **Writes** | insert/update/delete · upsert · bulk · `RETURNING` · savepoints · isolation levels · retry on transient conflict · `refresh` |
| **Schema** | composite PK and FK · polymorphic inheritance · views · triggers · indexes (partial, functional, `GIN`/`GIST`/`BRIN`) · checks · comments · enums · custom converters |
| **Engines** | PostgreSQL · MySQL/MariaDB · SQLite, all first class · `Cap` catalogue (`Full`/`Degraded`/`Nope`) · sync and async drivers · pool with `pre_ping`/`recycle`/timeout · statement timeout · `EXPLAIN` |
| **Migrations** | autodetected diff · atomic runner · `RebuildTable` for SQLite · `RunPython` with reverse · squash · cross-app dependencies · drift detection against the live database |
| **Tooling** | introspection and scaffold for the three engines · debug panel (`ssr`, `envelope`, `timing`, `sidecar`, `otel`) · index advisor · WSGI/ASGI/Django contrib · CLI |

Row by row, with links to the code, the test and the page: [feature index](docs/features.md).

---

## Architecture

```
Python class → Model Compiler → immutable metadata graph
                                        ↓
        SQL · migrations · query · session · CLI
```

```
decorators/  metadata/  compiler/  registry/  linker/
query/  expressions/  sql/  dialects/  drivers/  session/  migration/  cli/
```

Two axes that never mix: the **dialect** decides how SQL is *written* (placeholders, quoting,
`RETURNING`, `ON CONFLICT`); the **driver** decides how it is *executed*. Models and graph are
engine-agnostic — anything Postgres-specific reaching the model is a bug.

SQL is always parameterised: emission returns `(sql, params)` and values never enter the string.
That kills injection, and it is what makes multi-engine possible.

Async reuses the whole core: SQL generation does not execute, so it has no colour.

Details in [architecture](docs/contributors/architecture.md); how to work here in
[CONTRIBUTING](CONTRIBUTING.md).

---

## The type contract is a test

In `test/typing/`:

- `cases_positive.py` — what **must** type, with `assert_type`.
- `cases_negative.py` — what **must not compile**, each line carrying its `# EXPECT: <code>`.
- The runner requires mypy to report exactly those errors on exactly those lines, and pyright to
  reject the same ones.

Break `Truck.maker.nation.name` and the suite fails.

---

## Deliberately not built

- **Identity map and unit of work.** Two queries to the same row return two objects. Writes are
  explicit; nothing is flushed behind your back.
- **Lazy loading.** Touching an unloaded relation raises. This is what makes N+1 impossible by
  default.
- **Joined-table inheritance.** Single table with a discriminator covers the polymorphism, and its
  price is one rule: a child's own columns must allow `NULL`.
- **Model default ordering.** A hidden `ORDER BY` you did not write.

## Known limits

- `storage=NATIVE` in `snake_enum` (Postgres `CREATE TYPE`) is not built: `ALTER TYPE ... ADD VALUE`
  has no inverse, so its `down_sql` would be a lie. The default `CHECK` is reversible.
- CHECKs are declared outside the class body (`snake_checks(User, ...)`). Inside it, `__set_name__`
  has not run and the column does not know its own name.
- An expression does not carry its owning model in the type: `Maker.id` and `Truck.id` are twins to
  the checker. Encoding the owner would break deep navigation and condition composition; where it
  matters (aggregates, `.any()`) it is validated at runtime.
- No lazy loading, full-text search, JSON containment operators or array operators with a typed API.

The complete, current list is [known limits](docs/users/reference/limits.md) — part of the contract,
not a list of apologies.

---

## Status

Not published on PyPI. The distribution is named `snake-orm`, the import name is
`snakeorm`; both are explained in [release](docs/contributors/release.md).

Everything above is implemented and tested against real PostgreSQL, MySQL/MariaDB and SQLite. It has
not run in production yet, and that is the one thing a repository cannot give itself.
