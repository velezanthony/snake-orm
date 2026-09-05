# Migrations

Models are the source of truth. `makemigrations` compares what you declare against history and
generates a file with the difference.

```bash
uv run snakeorm makemigrations --models myapp.models   # writes migrations/0001_initial.py
uv run snakeorm migrate --models myapp.models          # applies them
uv run snakeorm status --models myapp.models           # which ones are applied
uv run snakeorm rollback --models myapp.models         # undoes the last one
```

## Running it from a web framework

Nothing to configure. Run the command from your project and it finds the application itself:

```bash
cd myproject        # where manage.py / main.py / app.py lives
uv run snakeorm tables
uv run snakeorm makemigrations --name add_notes
uv run snakeorm migrate
```

```python
# myproject/settings.py, main.py, app.py — wherever your entry point already is
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.contrib.config import SnakeOrmConfig

SNAKEORM = SnakeOrmConfig(
    databases={"default": SnakeConnectionConfig(backend=SnakeBackend.POSTGRES, name="mydb")},
    migrations_dir="migrations",
)
```

It works because the application already said everything the CLI needs. `SnakeOrmConfig` lives in
`snakeorm.contrib.config`; it is not a top-level export. Importing that module is also what runs
the `@snake_model` decorators. So the CLI looks for the entry point the way each framework itself
defines one (`manage.py` and its `DJANGO_SETTINGS_MODULE`, `main.py`, `app.py`, `wsgi.py`), imports
it, and takes the config out **by type**. There is no name to remember and no second file to write.

That the ENGINE comes from there too is the part worth noticing: `snakeorm migrate` runs on SQLite
and MySQL, not only on Postgres, because the config pairs driver and dialect and the CLI now asks
instead of assuming.

!!! tip "Prefer your framework's own command? Add it in one line"

    The executable works everywhere and needs nothing. If you would rather type what your framework
    taught you, the adapters carry no logic — they hand the arguments to the same CLI:

    ```python
    # myapp/management/commands/snakeorm.py      ->  manage.py snakeorm tables
    from snakeorm.cli.hooks import SnakeOrmCommand as Command
    ```

    ```python
    # your Flask factory                          ->  flask snakeorm tables
    from snakeorm.cli.hooks import flask_command

    app.cli.add_command(flask_command())
    ```

    FastAPI has no adapter, and that is deliberate: it has no command line of its own to hook into
    (`uvicorn main:app` is an argument to another program), so it uses the executable — which
    already needs nothing configured.

!!! danger "Your entry module must be importable without doing work"

    The CLI imports it, and that import is what registers the models. A module that opens
    connections, migrates or seeds at import time will do all of that because you asked to list your
    tables. Django's settings are constants and FastAPI puts its side effects in `lifespan`; in
    Flask, let the CLI find `create_app` instead of calling it yourself at the bottom of the file —
    the same discipline that stops `flask run --reload` re-seeding on every save. If you truly must
    do work at import, guard it with the `SNAKEORM_CLI` variable, which is set before importing.

!!! info "All three engines, on all three axes"

    Reading a schema is the third axis beside writing the SQL and executing it, and it now has an
    implementation per engine like the other two. `scaffold` and `check` work on PostgreSQL,
    MySQL/MariaDB and SQLite; the CLI picks the one that matches the connection your application
    declares, the same way it picks the driver and the dialect.

    ```bash
    snakeorm scaffold create --out mirror.py   # Postgres, MySQL/MariaDB or SQLite
    snakeorm check                             # drift: your models vs the real schema
    snakeorm fresh                             # wipe and rebuild from the migrations
    ```

    `fresh` too: emptying a schema is DDL, so each dialect writes its own — Postgres cascades,
    MySQL brackets the drops with its foreign-key switch, SQLite with the pragma.

    What a mirror gives back is not the exact inverse of what was written; see
    [db-first](../engines/db-first.md).

`status`, `tables`, `table` and `advise` round out the set: which migrations are applied, what the
models declare, one table in detail, and which foreign keys lack an index.

### When you need to say it yourself

`--models` and `--dsn` override discovery. `--models` is an import path (`myapp.models`, not
`myapp/models.py`) and stays REQUIRED for `makemigrations --only`, which is the one place it names
something discovery cannot guess: WHICH domain the migration is for. `--database` picks one
connection by name when the config declares several.

Not every command takes every flag — `makemigrations` and `squash` have no `--dsn`. Ask
`snakeorm <command> --help`.

With no application to find and no flags, the CLI stops and names the routes it tried. It never
falls back to a database nobody named.

## What's inside a file

Plain, readable Python. No frozen SQL; that's why the same migration works for two engines:

```python
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import AddColumn, CreateTable

operations = [
    CreateTable(
        SnakeTableInfo(
            name="users",
            columns=(
                SnakeColumnInfo(name="id", python_type=int, autoincrement=True),
                SnakeColumnInfo(name="email", python_type=str, unique=True),
            ),
            primary_key=SnakePrimaryKeyInfo(columns=(...,)),
        )
    ),
]
```

Each SCHEMA operation knows three things: its forward SQL (`up_sql`), its backward SQL (`down_sql`)
and how it mutates the abstract state (`apply_to_state`). That third one lets `makemigrations`
reconstruct the schema from history **without connecting** to the database.

A DATA operation is the other shape, and `RunPython` further down is one: it keeps
`apply_to_state` and swaps the two SQL halves for `run` and `unrun`, because it has no SQL of its
own to hand over — it takes a session and does the work itself. Its `apply_to_state` does nothing,
which is the honest answer: moving rows around changes no shape for the next migration to diff
against.

## What the autogen detects

Tables, columns, types, nullability, defaults, **indexes**, `UNIQUE` and `CHECK` constraints,
foreign keys (including `on_delete` changes), schemas, views, functions and triggers.

## Renaming a column

The diff sees a `DROP` + an `ADD`, and applying them **loses the data**. When it detects the pattern
it suggests on the console:

```
Warning: this could be a RENAME, and as it stands it DELETES the old column's data.
  - users: did you rename 'nickname' to 'nick'? Replace its DropColumn + AddColumn
    with RenameColumn(users, old_name="nickname", new_name="nick").
```

It suggests; it **doesn't decide**. Guessing a rename and getting it wrong would be worse than asking.

## In CI

```bash
uv run snakeorm makemigrations --models myapp.models --check   # exits != 0 if a migration is missing
uv run snakeorm check --models myapp.models                    # code vs the real DATABASE
```

The first catches "I forgot to generate the migration" (code vs history). The second catches
"someone touched the database by hand" (code vs real DB). You need both.

## Collapsing the history

```bash
uv run snakeorm squash --until 0042 --name initial
```

It generates a migration that **replaces** that stretch:

| Situation | What it does |
|---|---|
| None of the replaced ones applied | It runs it. Fresh install. |
| All applied | It marks it applied **without running it**. The DB is already like that. |
| Some yes and some no | **It stops and tells you.** |

The third case has no answer to guess: running would repeat; marking would skip what's missing. Both
corrupt.

!!! warning "Upgrading from a version before `type_params`"

    Column metadata changed shape: `int_size`, `max_length`, `json_storage`, `precision` and
    `scale` are no longer loose fields on `SnakeColumnInfo` — they travel inside a per-family
    `type_params` object. Migration files that were **already generated** write them the old way,
    so they **stop loading**.

    There is no compatibility shim, and that is deliberate: one path, no legacy. The way out is to
    squash the history as shown above and regenerate. If your database is already up to date, the
    resulting migration is marked applied without running anything, so no data is touched.

## Data migrations

To fill a new column from another one, DDL isn't enough:

```python
from snakeorm import SnakeQuery
from snakeorm.migration import AddColumn, RunPython

def fill(session):
    session.update_where(
        SnakeQuery(User).filter(User.nickname.is_null()),
        [(User.nickname, "")],
    )

def undo(session):
    ...

operations = [AddColumn(...), RunPython(fill, undo)]
```

`forward` and `backward` receive a `SnakeSession` over the **same** connection and transaction, so a
mixed migration (schema + data) is still all-or-nothing. They must be module-level functions, not
lambdas: the renderer writes them by reference.

!!! warning "Without `backward`, the rollback raises an explicit error"

    An irreversible data migration doesn't undo itself. The error tells you exactly what to add.

## Atomicity

PostgreSQL and SQLite both have transactional DDL, so each migration is **all or nothing**. The ORM
doesn't take that for granted: it reads it from `supports_transactional_ddl`. On an engine without it
(MySQL), the error says how many operations were applied before failing.

---

Next: the [runnable examples](examples.md) — the same API printed against a real database — or
straight to the [guide](../guide/columns.md), or [dialects](../engines/dialects.md) if you care about
what changes between engines.
