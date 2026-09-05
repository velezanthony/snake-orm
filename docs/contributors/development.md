# Development environment

```bash
make sync    # editable package + extras + every group, all of it
make audit   # the CI gate: lint + format + types + docs + tests
```

That is the minimum to start working. The rest is detail.

## Requirements

- Python 3.11+ (supports 3.11–3.14).
- [uv](https://docs.astral.sh/uv/) for the environment and the dependencies.
- Docker (optional) for a local PostgreSQL and a local MariaDB.

There is a **devcontainer** in `.devcontainer/`: in VS Code, "Reopen in Container" gives you
Python + PostgreSQL ready.

### One command, everything installed

```bash
make sync    # uv sync --all-extras --all-groups
```

`make sync` installs the editable package, **every extra** and **every dependency group**:

- extras `async` (`psycopg` 3), `mysql` (`pymysql`) and `otel` (`opentelemetry-api`),
- group `dev` (pytest, mypy, ruff, pyright, hypothesis),
- group `docs` (mkdocs-material, mkdocstrings, mkdocs-static-i18n),
- group `test-frameworks` (Django, Flask, FastAPI, httpx).

It is the same command CI runs in every job, and that matters: what the pipeline installs and what
your machine installs are the same thing, so the CI cannot discover anything you could not have
discovered first.

Do not fall back to a bare `uv sync`. It does not merely install less — uv syncs the environment to
what you asked for, so it **uninstalls** the `async` extra and the `docs` and `test-frameworks`
groups if they were already there. `make audit` calls `mkdocs build --strict`, so the next audit
would fail on a missing mkdocs that you had installed five minutes earlier.

If you deliberately want a subset, name it: `uv sync --group docs`, `uv sync --group
test-frameworks`.

## Databases

Unit tests run without any server. What each engine needs:

### SQLite — nothing

It ships in the standard library. `src/test/integration/test_sqlite_e2e.py`,
`test_sqlite_migrations.py` and `test_sqlite_introspection.py` never skip, on any machine.

### PostgreSQL — `docker compose`

```bash
cp .env.example .env   # ONE file: DB_BACKEND, the DB_* pieces, the MYSQL_* ones and the demos'
docker compose up -d db
make db-ready          # pg_isready against the configured host/port
```

`docker-compose.yml` reads the `.env`: it publishes `127.0.0.1:${DB_PORT}` mapped to 5432 inside
the container, so a fresh clone is consistent without editing anything.

The connection is resolved from the environment (or the `.env`) in `snakeorm/core/config.py`, which
is the single place that turns environment into a DSN. The pieces and their defaults:

| Variable | Default | What it is |
| --- | --- | --- |
| `DB_HOST` | `127.0.0.1` | host of the server |
| `DB_PORT` | `5432` | published port |
| `DB_USER` | `postgres` | user |
| `DB_PASSWORD` | `snakeorm_pass` | password |
| `DB_NAME` | `snakeorm_db` | database |

There is a second, named connection for the multi-database tests: `SNAKEORM_DSN_ANALYTICS`, a full
DSN. Only `default` is assembled from the `DB_*` pieces; every other name is read from
`SNAKEORM_DSN_<NAME>` and says exactly which variable is missing when it is.

### MySQL/MariaDB — `docker compose` too

`docker-compose.yml` has a `mysql` service (MariaDB 11) alongside `db`. It is **not** started by
`docker compose up -d db`, and that is the whole trap: name both.

```bash
docker compose up -d db mysql   # BOTH engines: the second one is not optional
docker ps --format '{{.Names}} {{.Ports}}'   # must match the .env, or the container is stale
```

It is MariaDB and not MySQL on purpose: `MySQLDialect` stands for both and they DISAGREE — measured,
`CREATE OR REPLACE FUNCTION` works on MariaDB 11.8 and answers `ERROR 1064` on MySQL 8.4. Where they
part ways the dialect DECLARES it, and `Cap.STORED_FUNCTIONS` says so in its own words: this dialect
serves both, so it cannot promise what only one of them does.

**Declaring is not the same as promising only the intersection, and one capability shows the
difference.** `statement_timeout_sql` emits `SET SESSION max_statement_time`, which is MariaDB's
variable — the two forks do not share it and neither accepts the other's, so no single spelling
serves both and there is no intersection to promise. The dialect emits MariaDB's, the fork the
project tests against, and Oracle's MySQL refuses it by name (`1193 Unknown system variable`) the
moment `TimeoutDriver` wraps the driver. That boundary is written down for users in
[Limits](../users/reference/limits.md); what belongs here is the reason it exists, because it is the
shape of every future case: a shared dialect can hide a difference only when one wording covers both
forks, and when none does, somebody has to lose.

The MySQL tests read their own variables, separate from the `DB_*` ones, and the `.env.example`
already carries the whole set, so `cp .env.example .env` is all you need. The defaults are the ones
the code falls back to when the variable is absent:

| Variable | Default in code | `.env.example` | Note |
| --- | --- | --- | --- |
| `MYSQL_HOST` | — | `localhost` | **no default**: without it the MySQL files skip |
| `MYSQL_PORT` | `3306` | `3307` | the compose file publishes `127.0.0.1:${MYSQL_PORT}:3306` |
| `MYSQL_USER` | `root` | `root` | |
| `MYSQL_PASSWORD` | empty | `snakeorm_pass` | also seeds `MARIADB_ROOT_PASSWORD` in compose |
| `MYSQL_DB` | `snakeorm_db` | `snakeorm_db` | also seeds `MARIADB_DATABASE` in compose |

The published port is **3307** and not 3306, so a MariaDB you may already have running locally does
not collide with this one.

`MYSQL_HOST` having no default is the sharp edge: without it, the three files
`src/test/integration/test_mysql_e2e.py`, `test_async_mysql_e2e.py` and
`test_mysql_introspection.py` skip in silence and the suite still reports green. The two switches
that turn that silence into a failure are the point of running it at all:

```bash
SNAKEORM_REQUIRE_POSTGRES=true SNAKEORM_REQUIRE_MYSQL=true uv run pytest -q
```

## Day-to-day commands

`make` or `make help` lists them, and it reads them out of the `Makefile` itself, so that listing
cannot go stale and this one can. Written out here, minus `help` above and the internal `coverage-run` that only `coverage`
calls:

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

Before opening a PR: `make audit` green.

## Repo structure

`src/` layout: **only the package is packaged**; the rest are siblings that do not enter the wheel.

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

`fields/` is where the descriptor system lives, which is the project's thesis. `linker/` resolves
the relationships between models; `introspection/` is the db-first path; `debug/` the panel;
`contrib/` the framework binders.

`dto/` is the youngest of them and the one you will not find on the facade: it reads the
`snake_dto(...)` declarations out of your own file with `ast` — never executing it — and the
`snakeorm dto --sync` command writes the TypedDicts back into a marked region of that same file —
without `--sync` it only reports, and exits 1 on drift. It is
imported as `from snakeorm.dto import ...` and deliberately NOT re-exported by `snakeorm/__init__.py`,
because it is still a prototype and the root package is a published surface with a documentation net
around it. Its user-facing page is
[Typed DTOs](../users/guide/typed-dtos.md).

Full design in [Architecture](architecture.md). Project rules and the PR workflow in the
[`CONTRIBUTING.md`](https://github.com/velezanthony/laboratorio-snake-orm/blob/main/CONTRIBUTING.md).
