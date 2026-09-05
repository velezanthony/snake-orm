# Contributing to SnakeORM

> The contributors' guide in English and Spanish: [https://velezanthony.github.io/laboratorio-snake-orm/contributors/](https://velezanthony.github.io/laboratorio-snake-orm/contributors/).
> This file is in English only, like the rest of the markdown at the repo root.

Thanks for the interest. SnakeORM is a **dataclass-first**, **type-first** ORM for Python 3.11+: the
type system is the single source of truth and the runtime only executes SQL over already-compiled
metadata. Before you touch code, this guide gets your environment ready and explains the rules of the
game.

## Development environment

The project uses [uv](https://docs.astral.sh/uv/) to manage the environment and the dependencies.

```bash
# Install EVERYTHING (package + optional extras + dev tooling)
uv sync --all-extras --all-groups
```

There is a **devcontainer** (`.devcontainer/`) that brings up Python and **both** engines ready to
use; if you use VS Code, "Reopen in Container" and there is nothing else to install.

The integration tests need **two** engines, not one. With Docker:

```bash
docker compose up -d db mysql   # Postgres and MariaDB (see docker-compose.yml)
```

Each engine reads its own variables from the environment (or a `.env`): Postgres takes `DB_HOST`,
`DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, and MySQL/MariaDB takes `MYSQL_HOST`, `MYSQL_PORT`,
`MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`. Copy `.env.example` to `.env` and adjust it.

A **Jaeger** trace viewer is also in the compose file, behind a profile so it never starts with the
engines. The `otel` debug channel exports to it: OTLP spans to
`http://localhost:4318/v1/traces` — the port this service publishes — overridable with
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. It is the one channel meant for production, because the
spans go to your collector and not into somebody's page.

```bash
docker compose --profile tracing up -d jaeger   # UI at http://127.0.0.1:16686, OTLP on 4317/4318
```

## Repo structure

`src/` layout: **only the package gets packaged**; the tests and everything else live under `src/` as
siblings but do NOT go into the wheel.

```
src/
├── snakeorm/     the package (flat domains: metadata, compiler, sql, dialects, drivers, ...)
├── test/         the suite (mirrors the structure of snakeorm/)
├── benchmarks/   performance measurement
└── examples/     executable examples
docs/             documentation (mkdocs)
```

The detailed design is in [`docs/contributors/architecture.md`](docs/contributors/architecture.md).

## Running the tests and the gates

```bash
make test           # the suite (uv run pytest)
make audit          # the full gate CI runs (lint + format + types + tests)
```

Or by hand:

```bash
uv run pytest                        # every test (see the warning below before trusting it)
uv run pytest -m "not integration"   # unit tests only, no DB
uv run ruff check .                   # lint
uv run ruff format --check .          # formatting
uv run mypy .                         # type-check of the package
make typecheck-frameworks             # type-check of frameworks/shared (it is TWO commands)
uv run mypy --strict src/snakeorm     # the "ZERO Any" gate over the package
uv run pyright src/snakeorm           # pyright (what Pylance sees)
uv run mkdocs build --strict          # the documentation builds without warnings
```

**Everything has to be green** before opening a PR.

CI runs the same gates and **one more the list above leaves out**: `make pyright-frameworks`, over
the three demo apps. `make audit` composes the whole set locally, so running that is the way to find
out what CI will say — the list above is what you reach for while working, not the contract.

### Running without a database is NOT verifying

Without the engines up, the tests that talk to a real server turn into SKIPS and **the suite comes
out green anyway**. Two gates, one per engine, turn "skipped for want of a server" into a failure:

```bash
SNAKEORM_REQUIRE_POSTGRES=true SNAKEORM_REQUIRE_MYSQL=true uv run pytest -q -rs
```

With both set, no skip can be down to a missing engine: the ones left over state a declared
capability (`MySQL cannot: STORED_FUNCTIONS`…). `-rs` prints each reason, and **the reason is the
criterion, not the count** — a skip that does not say "cannot" is a test nobody ran and nobody
missed.

## Project rules

- **Strict TDD**: the test comes FIRST, the implementation after.
- **Every test carries a docstring** `""" """` explaining WHAT it verifies.
- **ZERO `Any`**: `mypy --strict src/snakeorm` is the gate. The type always comes from Python; the
  metadata only adds SQL information.
- **The CODE speaks one language: English.** Identifiers, comments, docstrings, user-facing messages
  and any string the code carries. This section used to ask for comments in Spanish while the project
  was for learning; ever since the API reference is published, the repository has one language and
  one only. Keep them concise: explain the non-obvious "why", no essays.
- **The DOCUMENTATION speaks two**, and that is a separate decision not to be confused with the one
  above: two languages of prose over ONE SINGLE code base and the same examples. Every published page
  carries its `.es.md`, and the two share an identical code block — `test_docs_are_bilingual.py` and
  `test_docs_share_one_code.py` check it. A comment inside an example is code, not prose: it travels
  identically in both.
- **SQL is always parameterised**: emission returns `(sql, params)`; the values are NEVER interpolated
  into the string. No `repr()`/f-strings with values.
- **Acyclicity**: the packages do not import in circles (`test/test_layering.py` verifies it).
- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`...

## Adding an engine (dialect + driver)

The seam is split along two axes that never mix:

- **Dialect** — how the SQL is WRITTEN (placeholders, quoting, type mapping). It is a `Protocol`.
- **Driver** — how it is EXECUTED (the DBAPI library, connection, cursor, transaction). There are
  **two**, one synchronous and one asynchronous: generating SQL has no colour, so the dialect is
  reused as it is and the only thing written twice is the execution. The three current engines have
  the pair; if yours has no native async library, `threaded.py` serves the synchronous one from a
  thread of its own, which is what `aiosqlite` does under the hood.

Adding an engine must be **a new file, not a refactor**: one implementation of the dialect `Protocol`
in `dialects/` and the driver's ones in `drivers/`. The models and the metadata are 100%
engine-agnostic. See [dialects](docs/users/engines/dialects.md).

**And there is a third thing that is not optional: the `Cap` catalogue.** Your dialect answers the
ENTIRE capability catalogue with `Full()`, `Degraded(reason)` or `Nope(reason)`. It is not
documentation: if you leave one out, the ORM blows up when the dialect is imported, and deliberately
so — in a set, the capability you forgot to declare simply is not there, and "not there" reads as
"not supported". A silent default, in the ORM that shouts.

Out of that come the two things that make multi-engine credible: the plan stops in front of what the
engine cannot do, and the session warns ONCE per caveat. The reason you write in a `Degraded` is the
text a user is going to read, so tell them WHAT is degraded —ordering, comparing, operating— and not
that it "is not supported": a type with no equivalent falls back to `TEXT` and works, the value goes
in and comes out exact. What is never done is to store it worse and keep quiet.

## Working on the demos (`frameworks/`)

Three applications over ONE domain layer: Django and Flask render HTML, FastAPI answers JSON over an
`AsyncSession`. The framework carries no logic — it parses, calls `shared/` and renders.

The conventions (how an endpoint is declared in each one, why SSR uses only GET and POST, why neither
`contrib.auth` nor `flask-login` is used, and which nets are going to go red on you) are in [Working
on the demos](docs/contributors/frameworks.md). Read it BEFORE adding a route: half of those nets
exist because one demo grew a page the other two never had.

## Opening a Pull Request

1. Create a branch from `main`.
2. Test first, implementation after; leave `make audit` green.
3. Conventional commits, clear messages.
4. Open the PR describing the WHAT and the WHY.
