# Entorno de desarrollo

```bash
make sync    # editable package + extras + every group, all of it
make audit   # the CI gate: lint + format + types + docs + tests
```

Eso es lo mínimo para trabajar. Lo demás son detalles.

## Requisitos

- Python 3.11+ (soporta 3.11–3.14).
- [uv](https://docs.astral.sh/uv/) para el entorno y las dependencias.
- Docker (opcional) para PostgreSQL y MariaDB en local.

Hay un **devcontainer** en `.devcontainer/`: en VS Code, "Reopen in Container" te deja Python +
PostgreSQL listos.

### Un solo comando, todo instalado

```bash
make sync    # uv sync --all-extras --all-groups
```

`make sync` instala el paquete editable, **todos los extras** y **todos los grupos**:

- extras `async` (`psycopg` 3), `mysql` (`pymysql`) y `otel` (`opentelemetry-api`),
- grupo `dev` (pytest, mypy, ruff, pyright, hypothesis),
- grupo `docs` (mkdocs-material, mkdocstrings, mkdocs-static-i18n),
- grupo `test-frameworks` (Django, Flask, FastAPI, httpx).

Es el mismo comando que corre el CI en cada job, y eso importa: lo que instala el pipeline y lo que
instalas tú son la misma cosa, así que el CI no puede descubrir nada que tu máquina no hubiera
podido descubrir antes.

No vuelvas al `uv sync` pelado. No es que instale menos: uv sincroniza el entorno con lo que le
pides, así que **DESINSTALA** el extra `async` y los grupos `docs` y `test-frameworks` si ya
estaban. `make audit` llama a `mkdocs build --strict`, con lo que el siguiente audit fallaría por un
mkdocs que faltaba y que tenías instalado cinco minutos antes.

Si de verdad quieres solo una parte, nómbrala: `uv sync --group docs`, `uv sync --group
test-frameworks`.

## Bases de datos

Los tests unitarios corren sin ningún servidor. Lo que necesita cada motor:

### SQLite — nada

Viene en la biblioteca estándar. `src/test/integration/test_sqlite_e2e.py`,
`test_sqlite_migrations.py` y `test_sqlite_introspection.py` no se saltan nunca, en ninguna máquina.

### PostgreSQL — `docker compose`

```bash
cp .env.example .env   # ONE file: DB_BACKEND, the DB_* pieces, the MYSQL_* ones and the demos'
docker compose up -d db
make db-ready          # pg_isready against the configured host/port
```

`docker-compose.yml` lee el `.env`: publica `127.0.0.1:${DB_PORT}` mapeado al 5432 de dentro del
contenedor, así que un clon nuevo es coherente sin tocar nada.

La conexión se resuelve desde el entorno (o el `.env`) en `snakeorm/core/config.py`, que es el único
sitio que traduce entorno a DSN. Las piezas y sus defaults:

| Variable | Default | Qué es |
| --- | --- | --- |
| `DB_HOST` | `127.0.0.1` | host del servidor |
| `DB_PORT` | `5432` | puerto publicado |
| `DB_USER` | `postgres` | usuario |
| `DB_PASSWORD` | `snakeorm_pass` | contraseña |
| `DB_NAME` | `snakeorm_db` | base de datos |

Hay una segunda conexión con nombre para los tests multi-BD: `SNAKEORM_DSN_ANALYTICS`, un DSN
completo. Solo `default` se monta con las piezas `DB_*`; cualquier otro nombre se lee de
`SNAKEORM_DSN_<NAME>` y dice exactamente qué variable falta cuando falta.

### MySQL/MariaDB — `docker compose` también

`docker-compose.yml` tiene un servicio `mysql` (MariaDB 11) junto a `db`. **No** lo levanta
`docker compose up -d db`, y ahí está toda la trampa: nombra los dos.

```bash
docker compose up -d db mysql   # BOTH engines: the second one is not optional
docker ps --format '{{.Names}} {{.Ports}}'   # must match the .env, or the container is stale
```

Es MariaDB y no MySQL a propósito: `MySQLDialect` representa a los dos y NO coinciden —medido,
`CREATE OR REPLACE FUNCTION` funciona en MariaDB 11.8 y contesta `ERROR 1064` en MySQL 8.4—. Donde se
separan, el dialecto lo DECLARA, y `Cap.STORED_FUNCTIONS` viene con su motivo escrito: que este
dialecto sirve a los dos, así que no puede prometer lo que solo cumple uno.

**Declarar no es lo mismo que prometer solo la intersección, y hay una capacidad que enseña la
diferencia.** `statement_timeout_sql` emite `SET SESSION max_statement_time`, que es la variable de
MariaDB — los dos forks no la comparten y ninguno acepta la del otro, así que no hay una sola grafía
que sirva a ambos ni intersección que prometer. El dialecto emite la de MariaDB, el fork contra el que
el proyecto testea, y el MySQL de Oracle la rechaza por su nombre (`1193 Unknown system variable`) en
cuanto `TimeoutDriver` envuelve el driver. Ese límite está escrito para los usuarios en
[Límites](../users/reference/limits.es.md); lo que corresponde aquí es el motivo de que exista, porque
es la forma de todos los casos futuros: un dialecto compartido puede esconder una diferencia solo
cuando una redacción cubre a los dos forks, y cuando ninguna lo hace, alguien tiene que perder.

Los tests de MySQL leen sus propias variables, separadas de las `DB_*`, y el `.env.example` ya trae
el juego entero, así que con `cp .env.example .env` basta. Los defaults son a lo que recurre el
código cuando la variable no está:

| Variable | Default en código | `.env.example` | Nota |
| --- | --- | --- | --- |
| `MYSQL_HOST` | — | `localhost` | **sin default**: sin ella los ficheros de MySQL se saltan |
| `MYSQL_PORT` | `3306` | `3307` | el compose publica `127.0.0.1:${MYSQL_PORT}:3306` |
| `MYSQL_USER` | `root` | `root` | |
| `MYSQL_PASSWORD` | vacío | `snakeorm_pass` | alimenta también `MARIADB_ROOT_PASSWORD` en el compose |
| `MYSQL_DB` | `snakeorm_db` | `snakeorm_db` | alimenta también `MARIADB_DATABASE` en el compose |

El puerto publicado es el **3307** y no el 3306, para que una MariaDB que ya tengas corriendo en
local no choque con ésta.

Que `MYSQL_HOST` no tenga default es el borde afilado: sin ella, los tres ficheros
`src/test/integration/test_mysql_e2e.py`, `test_async_mysql_e2e.py` y
`test_mysql_introspection.py` se saltan en silencio y la suite sigue dando verde. Los dos
interruptores que convierten ese silencio en un fallo son el sentido de correrlo:

```bash
SNAKEORM_REQUIRE_POSTGRES=true SNAKEORM_REQUIRE_MYSQL=true uv run pytest -q
```

## Comandos del día a día

`make` o `make help` los lista, y los lee del propio `Makefile`, así que ese listado no puede quedarse
obsoleto y éste sí. Escritos aquí, menos `help` de arriba y el interno `coverage-run` al que solo llama `coverage`:

```bash
# Dependencies
make sync                     # uv sync --all-extras --all-groups (everything)
make lock                     # regenerate uv.lock

# Quality
make lint                     # ruff check
make format                   # ruff format (writes)
make format-check             # ruff format --check (does not write)
make typecheck                # mypy . (see the Makefile)
make typecheck-frameworks     # mypy over frameworks/shared (run from frameworks/, NOT optional)
make typecheck-strict         # mypy --strict over the package: the "ZERO Any" gate
make pyright                  # pyright: what Pylance sees by default
make pyright-frameworks       # pyright over the three demo apps in frameworks/
make typecheck-react          # tsc over the React client (the fourth demo)
make lint-react               # ESLint over the React client
make docs-build               # mkdocs build --strict
make audit                    # the full read-only gate (all of the above + tests)
make fix                      # ruff check --fix + ruff format

# Tests
make test                     # pytest -q
make test-v                   # pytest -v

# Coverage
make coverage                 # coverage of BOTH suites, with the lines that never ran
make coverage-html            # the same, as HTML (htmlcov/)
make coverage-domains         # rolled up per domain, one line per subpackage: WHERE to look
make coverage-snapshot        # record a timestamped snapshot and rebuild what reads it
make coverage-chart           # rebuild the snapshot manifest without measuring again
make coverage-css             # copy the built stylesheet next to the snapshot viewer
make coverage-serve           # serve the snapshot viewer so it can fetch its snapshots

# Examples and benchmarks  (executable documentation; they DEMAND a real Postgres)
make examples                 # the published tour + its assertions (in the gate)
make benchmarks               # full performance measurement (a measurement: NOT in the gate)
make benchmarks-smoke         # the benchmark harness still runs, minimal sizes (in the gate)

# Database
make db-ready                 # pg_isready against the configured connection
make db-shell                 # psql shell against the database

# Demo apps in frameworks/  (the test-frameworks group, installed by make sync)
make flask-dev                # Flask demo (SSR + API) on :5000
make django-dev               # Django demo (SSR + API) on :8080
make fastapi-dev              # FastAPI demo (API only) on :8001
make react-dev                # React client (the fourth demo) on :5173. NEEDS a backend up
make seed FW=flask SCALE=massive   # seed one demo at one scale
make frameworks-test          # the three apps + the shared layer
make frameworks-test-shared   # only the shared domain
make frameworks-test-flask    # only Flask
make frameworks-test-django   # only Django
make frameworks-test-fastapi  # only FastAPI
# The shared suite demands a REAL Postgres: without one, its two-connection tests skip and
# the suite still reports green. Turn it off deliberately on a machine without docker:
# SNAKEORM_REQUIRE_POSTGRES=false make frameworks-test

# Cleanup
make clean                    # tool caches and bytecode
```

Antes de abrir un PR: `make audit` en verde.

## Estructura del repo

Layout `src/`: **solo el paquete se empaqueta**; el resto son hermanos que no entran en el wheel.

```text
src/
├── snakeorm/     the package: one subpackage per domain, all of them here
│   ├── core/         cross-cutting identity (base model, exceptions, signals, config)
│   ├── helpers/      generic utilities reused by several domains
│   ├── metadata/ compiler/ registry/     model → metadata graph
│   ├── decorators/ fields/               @snake_model and the descriptor system (the thesis)
│   ├── linker/                           resolves the relationships between models
│   ├── query/ expressions/ sql/          SQL construction and emission
│   ├── dialects/ drivers/ session/       how it is written and how it is executed
│   ├── migration/ introspection/         schema evolution
│   ├── dto/                              declared shapes -> TypedDicts, written by the CLI
│   └── debug/ contrib/ cli/              tooling
├── test/         the suite (mirrors the structure of snakeorm/)
├── benchmarks/   performance measurement
└── examples/     runnable examples
```

`fields/` es donde vive el sistema de descriptores, o sea la tesis del proyecto. `linker/` resuelve
las relaciones entre modelos; `introspection/` es el camino db-first; `debug/` el panel; `contrib/`
los enlazadores de framework.

`dto/` es el más joven de todos y el que no encontrarás en la fachada: lee las declaraciones
`snake_dto(...)` de tu propio fichero con `ast` —sin ejecutarlo jamás— y el comando `snakeorm dto --sync`
escribe los TypedDicts de vuelta en una región marcada de ese mismo fichero. Se importa como
`from snakeorm.dto import ...` y a propósito NO lo re-exporta `snakeorm/__init__.py`, porque sigue
siendo un prototipo y el paquete raíz es una superficie publicada con una red de documentación
alrededor. Su página de usuario es
[DTOs tipados](../users/guide/typed-dtos.es.md).

Diseño completo en [Arquitectura](architecture.es.md). Reglas del proyecto y flujo de PR en el
[`CONTRIBUTING.md`](https://github.com/velezanthony/snake-orm/blob/main/CONTRIBUTING.md).
