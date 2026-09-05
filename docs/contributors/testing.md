# Testing

```bash
uv run pytest                        # the whole suite
uv run pytest -m "not integration"   # deselects the MARKED ones, which is not "no database"
uv run pytest src/test/session/      # one directory
uv run pytest -q -k upsert           # by name
```

**`-m "not integration"` is not a promise of "no server".** It deselects the tests that CARRY the
marker, and the marker is written by hand, file by file. Files under `test/integration/` that talk to
a real engine go without it — `test_mysql_e2e.py`, `test_async_mysql_e2e.py`,
`test_round_trip_property.py`, `test_session_database_isolation.py` and a handful under
`test/migration/` among them — so with the containers up that filter runs them against the real
server. If what you want is to touch nothing, name the directories you DO want instead of trusting a
filter to exclude what you do not.

**Strict TDD**: the test first, the implementation after. Every test carries a `""" """` docstring
explaining WHAT it verifies.

The tests live in `src/test/` and **mirror `src/snakeorm/`**: the one for
`snakeorm/metadata/column.py` is in `test/metadata/`. It is an index, not architecture duplication.

How many there are is not written down here, because a number in prose goes stale the week after it
is typed and then reads as a fact. This is the command:

```bash
uv run pytest --collect-only -q | tail -1        # how many the suite collects today
```

## Test types

- **Unit** — the majority. No database.
- **Integration** — they talk to a real server, and **no directory is a reliable signal either**:
  most live in `test/integration/`, `test/scenarios/` and part of `test/migration/`, but there are
  also files under `test/cli/`, `test/dto/`, `test/session/`, `test/examples/` and
  `test/benchmarks/`. What DOES answer is what a file imports — `NO_SERVER_REASON` or
  `NO_MYSQL_REASON` from `test/conftest.py` — and the honest way to run the set is to raise the
  containers and put the `SNAKEORM_REQUIRE_*` gates up, so a missing engine is a failure rather than
  a skip. `@pytest.mark.integration`
  covers most of them and NOT all — it is written by hand, so treating it as the definition of the
  set is the mistake the first section warns about. Not every one of them needs a server either:
  `test/integration/test_sqlite_e2e.py`, `test_sqlite_migrations.py` and
  `test_sqlite_introspection.py` run on any machine, because SQLite ships in the standard library
  (and none of the three carries the marker). The PostgreSQL ones **skip gracefully** without a
  server, and the three MariaDB files (`test_mysql_e2e.py`, `test_async_mysql_e2e.py`,
  `test_mysql_introspection.py`) skip without `MYSQL_HOST`. See
  [When a skip is a failure](#when-a-skip-is-a-failure).
- **Type contract** (`@pytest.mark.typecheck`) — `test/typing/` runs mypy AND pyright over
  `cases_positive.py` (must type-check) and `cases_negative.py` (must fail EXACTLY on the lines with
  `# EXPECT: <code>`). Slow; excluded with `-m "not typecheck"`.
- **Property-based** — [Hypothesis](https://hypothesis.readthedocs.io/) declares the invariant and
  searches for the input that breaks it, instead of enumerating cases somebody thought of.
  `test/test_pyliteral_property.py`: for ANY string, `str_lit` produces a parseable literal that
  evaluates back to the exact same string (a security primitive — a leak there is RCE in the
  scaffolder). `test/integration/test_round_trip_property.py`: for ANY value of ANY supported type,
  what is written comes back identical, on both engines. When something breaks, Hypothesis minimises
  it to the smallest failing example.

## The mechanical safety nets

These are not tests of a feature. Each one nails down a convention that used to erode silently, and
each one exists because it already eroded once.

- **Acyclicity** — `test/test_layering.py`: fails if two packages import each other in a cycle.
  Measured by PACKAGE, not by module. Before it existed there was one real cycle
  (`decorators <-> query`) and twenty-eight imports hidden inside functions.
- **Docs compile** — `test/test_docs.py`: every ```` ```python ```` block in `docs/` parses, every
  `from snakeorm import X` really exists, and every model the docs declare COMPILES. The third
  check is the one that catches the expensive lie: `snake_column()` over a `datetime` imports a name
  that exists, parses fine, and is a compiler error. Pseudo-code goes in ```` ```text ````, REPL
  transcripts in ```` ```pycon ````.
- **Docs are bilingual** — `test/test_docs_are_bilingual.py`: every published page exists in BOTH
  languages (`page.md` English, `page.es.md` Spanish). `mkdocs-static-i18n` falls back to the
  default language, so an untranslated page never breaks the build — which is exactly what makes the
  drift invisible. It checks that the page EXISTS; whether the two say the same thing is not
  something a test can measure.
- **The type table** — `test/test_type_table_doc.py`: reads the three-column table in
  `docs/users/guide/columns.md` (Postgres, MySQL, SQLite) and asks the dialect that produces it. It
  had already drifted: it claimed MySQL "rejects" `SnakeUtc`, `timedelta` and `list[int]` when all
  three fall back to TEXT. A new row without an entry here fails too — a half-written table lies as
  much as a wrong one.
- **The language of the code is a convention, not a net.** Three detectors used to live here and
  have been deleted: they found Spanish by LISTING Spanish, and a blocklist fails OPEN — it only
  ever finds what it already knows. A test named "the strings are English" that checks "no string
  matched my list" is worse than no test, because it manufactures confidence. The convention stands
  unchanged, the code speaks English; what is gone is the detector that pretended to guarantee it.
  An EXISTENCE and an EQUALITY can be checked mechanically, a language cannot.
- **The anti-skip net itself** — `test/test_ci_guard.py`: `conftest.py` recognises a
  missing-server skip by its REASON, which is a convention, and conventions erode. This ties that
  phrase to the real test tree, so the day somebody words it differently the test fails instead of
  quietly falling out of the net.
- **The public API** — `test/test_public_api.py`: `snakeorm/__init__.py` is a facade that re-exports
  with a redundant alias and no `__all__`, so the public surface is DERIVED at runtime rather than
  kept as a parallel list of strings. The contract: the minimum surface to declare, query and
  execute is published, and NOTHING foreign (stdlib or third-party) leaks into it.

## The dialect matrices

This is the first thing that breaks for anyone touching a dialect, and the project has a recurring
bug shape: **something implemented or verified in N-1 of N siblings**. Foreign keys existed in
Postgres and not in SQLite. `AsyncSession` shipped with twelve of twenty-two methods.

- `src/test/migration/test_emitter_dialect_matrix.py` — every DDL emitter against the three
  engines. How many there are is not written here and not written there either:
  `test_the_invocation_table_covers_every_emitter` READS them out of `migration/ddl.py`, so a new
  emitter joins the matrix by existing. It does not demand that everything works everywhere; it demands that each emitter
  does ONE of two things: emit SQL the engine ACCEPTS, or be stopped by `realize()` in the PLAN with
  a readable reason. The forbidden third option is emitting SQL the engine rejects, so it blows up
  with a cryptic syntax error in the middle of a deployment.
- `src/test/integration/test_query_dialect_matrix.py` — every QUERY path that emits a correlated
  subquery. It runs behaviour with real data instead of enumerating names, and it covers a blind
  spot the other nets left: seven public APIs (`.any()`, `.count()`, `.sum_()`, `.avg()`, `.min_()`,
  `.max_()`, `session.annotate()`) were broken on SQLite because two emitters built the child table
  reference by hand instead of going through `qualified()`. Tested on SQLite because that is where
  the absence of schemas exposes it.

## When a skip is a failure

A test that skips in silence is worse than a test that does not exist.

The tests that talk to Postgres skip gracefully when there is no server, and that is RIGHT on the
laptop of somebody who only wants to touch the compiler. In CI it is exactly the opposite: the
server has to be there, and a `skip` means the infrastructure failed and the suite covered it up.

Nobody reads the `skipped` count; everybody reads whether it says `passed`, so a badly propagated
`DB_PORT` can leave a hundred integration tests skipping and the suite still reporting green.

```bash
SNAKEORM_REQUIRE_POSTGRES=true uv run pytest
```

With that variable set, a skip for lack of a database is reported as a FAILURE, naming the test and
the original reason. `.github/workflows/ci.yml` sets it on the postgres leg of the matrix.

**The value is read as an allow-list, and there is ONE spelling per side.** Unset is off, `true` and
`false` decide, and anything else stops the run before collection saying what it read:

```text
ERROR: SNAKEORM_REQUIRE_POSTGRES='0' is not a boolean: write 'true' or 'false', or leave it unset. It is not guessed either way, and that is deliberate — reading it as on would hide a switch you meant to turn off, and reading it as off would hide the very skips this net exists to make loud.
```

So `false` is off, and `0`, `no`, `off` and `1` are not "off": they abort. That is the fix for what
this used to be — a blocklist where `0`, `false` and `no` meant off and ANYTHING else meant on, so
`SNAKEORM_REQUIRE_POSTGRES=off` read to a person as plainly off and switched the net ON, in silence.
A longer list has the same shape and only moves the edge; refusing to guess removes it, and both
possible guesses are wrong in the same way — one hides a switch you meant to turn off, the other
hides the very skips this net exists to make loud.

**The net triggers on the REASON of the skip, not on the folder.** The first version looked at a
list of directories (`integration`, `scenarios`) and missed two files in `test/migration` that also
need a server — precisely the atomicity and data-migration ones, which are among the most painful
not to run. A list of places has to be maintained and goes stale; the reason travels with the test,
so a new file in a new folder is covered without its author having to know any of this exists.

CI adds a second check on top, because the hook cannot catch what is never collected at all (a
broken `conftest`, a stray `--ignore`, a renamed directory): it counts the collection of
`src/test/integration` and `src/test/scenarios` and fails under 100. The threshold is a floor and
not a target, so it is the only figure here: what they collect today is
`uv run pytest --collect-only -q src/test/integration src/test/scenarios | tail -1`.

## Environment variables

| Variable | Default | What it does |
| --- | --- | --- |
| `SNAKEORM_REQUIRE_POSTGRES` | off | a skip for lack of PostgreSQL becomes a failure |
| `SNAKEORM_REQUIRE_MYSQL` | off | the same, for the MySQL/MariaDB server |
| `DB_HOST` | `127.0.0.1` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | `snakeorm_pass` | PostgreSQL password |
| `DB_NAME` | `snakeorm_db` | PostgreSQL database |
| `SNAKEORM_DSN_<NAME>` | — | full DSN for a NAMED connection (multi-database tests) |
| `MYSQL_HOST` | — | **no default**: without it `test_mysql_e2e.py` skips entirely |
| `MYSQL_PORT` | `3306` | MariaDB/MySQL port |
| `MYSQL_USER` | `root` | MariaDB/MySQL user |
| `MYSQL_PASSWORD` | empty | MariaDB/MySQL password |
| `MYSQL_DB` | `snakeorm_db` | MariaDB/MySQL database |

The `DB_*` set is resolved in `snakeorm/core/config.py`, the single place that turns environment
(including the `.env`) into a DSN. How to raise each server is in
[Development environment](development.md#databases).

## Coverage

```bash
make coverage        # report in the terminal, with the missing lines
make coverage-html   # browsable report in htmlcov/
```

Configured in `pyproject.toml` with `branch = true` and `source = ["snakeorm"]`. `@overload`,
`if TYPE_CHECKING:` and bodies that are literally `...` are excluded: an overload is a signature
with no body that nobody ever executes (`session.py` has four in a row just for `select`), and
counting them as uncovered measures the style of the code rather than what the suite exercises.

**There is deliberately no `fail_under`, and this is not an oversight to fix.** The decision is to
MEASURE AND REPORT. A threshold picked by eye always ends up in one of two places: blocking a good
change, or being lowered until it means nothing. CI already measures it — on the postgres leg, not
the SQLite one, because without a server the integration tests skip and the number would come out
low for a reason that has nothing to do with the quality of the suite.

## The demo apps

```bash
make frameworks-test          # the three apps + the shared layer
make frameworks-test-shared   # only the shared domain
make frameworks-test-flask    # only Flask
make frameworks-test-django   # only Django
make frameworks-test-fastapi  # only FastAPI
```

The three apps in `frameworks/` are the ONLY place where the pipeline is exercised end to end for
real: model → compiler → metadata graph → migration → DDL → session → HTTP, against a real database
(SQLite) and with the migrations applying. The `src/test` suite proves each stretch; this proves the
stretches fit together.

They gate in CI as their own job, with a four-leg matrix (`shared`, `fastapi`, `flask`, `django`)
and `fail-fast: false`, so a red check already says WHICH one broke. `shared` goes first: it is the
domain the three apps share, so a failure there is three derived failures from a single cause.

## The gates (what CI demands)

```bash
uv run ruff check .                  # lint, over the WHOLE repo
uv run ruff format --check .         # formatting, over the WHOLE repo
uv run mypy .                        # type-check of the repo (lenient)
cd frameworks && uv run mypy shared  # the demos' shared layer (NOT optional)
uv run mypy --strict src/snakeorm    # the "ZERO Any" gate over the package
uv run pyright src/snakeorm          # pyright (what Pylance sees by default)
uv run pyright frameworks/django frameworks/flask frameworks/fastapi   # pyright over the demos
uv run mkdocs build --strict         # the documentation builds with no warnings
uv run pytest                        # the suite
make frameworks-test                 # the three demo apps + the shared layer
```

**The two ruff lines say `.` and not `src`, and that is the point.** They look at the WHOLE repo,
`frameworks/` included, because the alternative already failed: with the targets pinned to `src/`, a
badly formatted demo file came out green locally and red in the pipeline — and it was not
hypothetical, there were three unformatted demo files sitting on `main` while `make audit` said all
was well. A gate that advertises "what CI demands" and looks at less is the incomplete gate claiming
to be complete.

`make audit` runs those and MORE: it is a SUPERSET of the CI gates, and the prerequisite list lives on
the `audit:` line of the `Makefile` rather than being copied here, because a list copied by hand is a
list that goes stale. What it adds beyond this block is `typecheck-react` and `lint-react` for the
React client, plus `examples` and `benchmarks-smoke`. Those last two sit deliberately JUST BEFORE
`test`, and the position is the decision: both demand Postgres and take seconds, while `test` takes
minutes and without Postgres it skips in green. In front, a blind `make audit` stops in second three
saying there is no database instead of spending two minutes manufacturing confidence.
**Everything has to be green.** `pyright-frameworks` is the one that is easy to leave out of a list
written by hand: it is the demos' half of what `make pyright` does for the package, and it exists
because `pyright` was pinned to `src/snakeorm` while the three apps went unchecked.

The second type-check is not optional. `frameworks/shared/` imports itself as `shared`, which does
not resolve from the repo root: run from there, mypy turns the whole layer into `Any` and reports
Success. It is checked FROM `frameworks/`, where `shared` resolves.

Two of them deserve their reason stated. `mypy --strict` runs over the PACKAGE and not the repo:
that is the project's thesis gated ("zero `Any`"), and making it global would force the tests to be
strictly typed too. `pyright` is checked in basic mode, the Pylance default, because pyright's
strict mode flags the internal `Any` of the recursive descriptors — which is the project's own
technique — so gating it would mean fighting the design.

## Rules when writing tests

- Test FIRST (red), then implementation (green).
- Mandatory docstring stating what it verifies.
- For SQL, check the emitted `(sql, params)`; do not interpolate values.
- End-to-end in `test/integration/` and `test/scenarios/`.
- If a test needs a server, skip with the repo's phrase — the one `test/conftest.py` publishes — so
  the anti-skip net covers it. Inventing a wording leaves it outside, and `test_ci_guard.py` will
  say so.
- Touching a dialect: the two matrices above, before anything else.
- Every new migration structure: full-cycle test
  (model → `autodetect` → file → `replay` → identical state).
