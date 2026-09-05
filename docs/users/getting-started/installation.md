# Installation

```bash
uv sync --all-extras --all-groups   # from the root of a checkout of the repository
```

!!! warning "It is not on PyPI yet"

    `pip install snakeorm` does not work, and neither does `pip install laboratorio-snake-orm`: no
    version has ever been published, and `git tag` returns nothing. Until there is a release, the
    way in is a checkout of the repository, and the command above is run from its root.

    The two names are not a typo. `pyproject.toml` declares `name = "laboratorio-snake-orm"` — the
    **distribution** name, the one you install — while the package you import is `snakeorm`, the
    **import** name. That split is legal, common, and what you will type the day there is a
    release: `pip install laboratorio-snake-orm`, then `import snakeorm`. The whole story is in
    [the release process](../../contributors/release.md).

Needs **Python 3.11+**: deep typing uses `dataclass_transform` (PEP 681) and the `X | None` syntax
in annotations.

## Your engine's driver

Three engines, all three first class: **PostgreSQL**, **MySQL/MariaDB** and **SQLite**. You pair a
dialect with a driver; only MySQL needs an extra install:

=== "PostgreSQL"

    ```bash
    # nothing to install: psycopg2-binary is a dependency of snakeorm
    ```

    ```python
    from snakeorm import PostgresDialect, PsycopgDriver

    driver = PsycopgDriver.connect("postgresql://user:pass@localhost/mydb")
    dialect = PostgresDialect()
    ```

=== "MySQL / MariaDB"

    ```bash
    uv sync --extra mysql     # brings PyMySQL
    ```

    ```python
    from snakeorm import MySQLDialect, PyMySQLDriver

    driver = PyMySQLDriver.connect(
        host="localhost", user="user", password="pass", database="mydb"
    )
    dialect = MySQLDialect()
    ```

    MySQL takes connection **arguments**, not a one-piece DSN. That's the engine's shape, and the
    driver doesn't invent a DSN parser to hide it.

    PyMySQL is pure Python, so it installs anywhere without a C toolchain. `mysqlclient` is faster
    and works just as well: it speaks the same `%s` placeholders, so the dialect does not change.

=== "SQLite"

    ```bash
    # nothing to install: sqlite3 ships in the stdlib
    ```

    ```python
    from snakeorm import SQLiteDialect, SQLiteDriver

    driver = SQLiteDriver.connect("./my.db")  # or ":memory:"
    dialect = SQLiteDialect()
    ```

## The same, asynchronously

Generating SQL has no color — it doesn't execute — so the **dialect doesn't change**. Only the driver
does, and the session you pair it with (`AsyncSession` instead of `SnakeSession`):

=== "PostgreSQL"

    ```bash
    uv sync --extra async     # brings psycopg 3
    ```

    ```python
    from snakeorm import AsyncPsycopgDriver, PostgresDialect

    driver = await AsyncPsycopgDriver.connect("postgresql://user:pass@localhost/mydb")
    dialect = PostgresDialect()
    ```

=== "MySQL / MariaDB"

    ```bash
    uv sync --extra mysql     # the SAME extra as the synchronous path
    ```

    ```python
    from snakeorm import AsyncPyMySQLDriver, MySQLDialect

    driver = await AsyncPyMySQLDriver.connect(
        host="localhost", user="user", password="pass", database="mydb"
    )
    dialect = MySQLDialect()
    ```

=== "SQLite"

    ```bash
    # nothing to install here either
    ```

    ```python
    from snakeorm import AsyncSQLiteDriver, SQLiteDialect

    driver = await AsyncSQLiteDriver.connect("./my.db")  # or ":memory:"
    dialect = SQLiteDialect()
    ```

!!! note "There is no extra just for asynchronous MySQL"

    Two extras buy a driver: `async` (psycopg 3) and `mysql` (PyMySQL). Only **PostgreSQL** has a native asynchronous driver, and that is what `async` buys.
    MySQL and SQLite serve their synchronous driver from a thread of their own, so they need nothing
    beyond what you already installed.

!!! note "Why the driver is your job"

    They are two distinct axes: the **dialect** decides how the SQL is WRITTEN (placeholders,
    quoting, `LIMIT`); the **driver** decides how it is EXECUTED. Making them parameters and not a
    magic factory is what lets you wrap the driver with a logger or a pool without the rest noticing.
    See [dialects](../engines/dialects.md).

## Configuration

Connections are read from environment variables or a `.env`:

```bash
DATABASE_URL=postgresql://user:pass@localhost/mydb
```

`SNAKEORM_DSN` and the classic `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` also
work. For several databases at once, see [multiple databases](../engines/multi-connection.md).

## Check that it works

```python
from snakeorm import PostgresDialect, PsycopgDriver, SnakeSession, SnakeRow, snake_row

@snake_row
class Version(SnakeRow):
    value: str

dsn = "postgresql://user:pass@localhost/mydb"
session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
print(session.raw("SELECT version() AS value", into=Version)[0].value)
```

## The tools this project takes for granted

Everything that sets this ORM apart lives in the type-checker. Both live in the `dev` group, so
the sync above already brought them:

```bash
uv run mypy .          # must pass
uv run pyright         # and agree with mypy
```

Without them, the deep typing that sets this ORM apart is invisible.

---

Next: [your first model](first-model.md).
