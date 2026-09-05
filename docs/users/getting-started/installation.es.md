# Instalación

```bash
pip install snake-orm==0.1.0b1   # or: pip install --pre snake-orm
```

!!! warning "La versión se fija porque es una beta"

    `pip install snake-orm` a secas no instala NADA: pip no recoge una versión preliminar salvo
    que se pida por su nombre o con `--pre`. Ese es el sentido de publicar una beta — que nadie
    acabe en ella sin querer mientras la API todavía se mueve.

    `pip install snakeorm` tampoco funciona, y los dos nombres no son una errata.
    `pyproject.toml` declara `name = "snake-orm"` — el nombre de **distribución**, el que se
    instala — mientras que el paquete que se importa es `snakeorm`, el nombre de **importación**.
    La historia entera está en [el proceso de release](../../contributors/release.es.md).

Desde una copia del repositorio, para trabajar sobre el propio ORM:

```bash
uv sync --all-extras --all-groups   # from the root of the checkout
```

Necesita **Python 3.11+**: el tipado profundo usa `dataclass_transform` (PEP 681) y la sintaxis
`X | None` en anotaciones.

## El driver de tu motor

Tres motores, los tres de primera clase: **PostgreSQL**, **MySQL/MariaDB** y **SQLite**. Emparejas
un dialecto con un driver; solo MySQL necesita instalar algo aparte:

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

    MySQL recibe **argumentos** de conexión, no un DSN de una pieza. Es la forma del motor, y el
    driver no se inventa un parser de DSN para taparla.

    PyMySQL es Python puro, así que se instala en cualquier sitio sin toolchain de C. `mysqlclient`
    es más rápido y sirve igual: habla los mismos placeholders `%s`, así que el dialecto no cambia.

=== "SQLite"

    ```bash
    # nothing to install: sqlite3 ships in the stdlib
    ```

    ```python
    from snakeorm import SQLiteDialect, SQLiteDriver

    driver = SQLiteDriver.connect("./my.db")  # or ":memory:"
    dialect = SQLiteDialect()
    ```

## Lo mismo, en asíncrono

Generar SQL no tiene color —no ejecuta—, así que el **dialecto no cambia**. Solo cambian el driver y
la sesión con la que lo emparejas (`AsyncSession` en vez de `SnakeSession`):

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

!!! note "No hay un extra solo para MySQL asíncrono"

    Dos extras compran un driver: `async` (psycopg 3) y `mysql` (PyMySQL). Solo **PostgreSQL** tiene driver asíncrono nativo, y es lo que compra `async`.
    MySQL y SQLite sirven su driver síncrono desde un hilo propio, así que no necesitan nada más allá
    de lo que ya instalaste.

!!! note "Por qué el driver es cosa tuya"

    Son dos ejes distintos: el **dialecto** decide cómo se ESCRIBE el SQL (placeholders, quoting,
    `LIMIT`); el **driver** decide cómo se EJECUTA. Que sean parámetros y no una fábrica mágica es lo
    que permite envolver el driver con un logger o un pool sin que el resto se entere.
    Ver [dialectos](../engines/dialects.es.md).

## Configuración

Las conexiones se leen de variables de entorno o un `.env`:

```bash
DATABASE_URL=postgresql://user:pass@localhost/mydb
```

También valen `SNAKEORM_DSN` y las clásicas `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` /
`DB_PASSWORD`. Para varias bases a la vez, mira
[varias bases de datos](../engines/multi-connection.es.md).

## Comprobar que va

```python
from snakeorm import PostgresDialect, PsycopgDriver, SnakeSession, SnakeRow, snake_row

@snake_row
class Version(SnakeRow):
    value: str

dsn = "postgresql://user:pass@localhost/mydb"
session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
print(session.raw("SELECT version() AS value", into=Version)[0].value)
```

## Las herramientas que este proyecto da por sentadas

Todo lo que distingue a este ORM vive en el type-checker. Los dos viven en el grupo `dev`, así que
el sync de arriba ya los trajo:

```bash
uv run mypy .          # must pass
uv run pyright         # and agree with mypy
```

Sin ellos, el tipado profundo que distingue a este ORM es invisible.

---

Siguiente: [tu primer modelo](first-model.es.md).
