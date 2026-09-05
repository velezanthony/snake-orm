# Demo apps — Django · Flask · FastAPI

Three apps that use **SnakeORM** to mount the SAME domain on each framework, with the **ORM's debug
tool** wired in. They serve as an example and as a real integration test: they exercise the
`snakeorm.contrib` adapters against the real Django, Flask and FastAPI.

The domain is ten packages and 29 tables. SIX have SSR pages and each one teaches something
different on purpose: **blog** (login/register + post CRUD) is the everyday shape —relationships
without N+1, a many-to-many of tags—; **inventory** is the hard one — stock is identified by the
PAIR `(warehouse, sku)`, so the key travels through the URL in two halves and the movements hang off
a two-column foreign key—; **orders** is the only section where two customers want the same unit;
**billing** is the money, read-only on purpose; **taxonomy** is the many-to-many with an explicit
bridge; and **logistics** is the one that MEASURES — the distance to a depot is a square root over a
sum of squares, and the load of an hour is a window whose width is a VALUE and not a number of rows.
The other four are JSON only. Where this is heading, further down.

## Structure

```
frameworks/
├── shared/          código compartido (fuente ÚNICA de verdad)
│   ├── data/          datos de siembra (definidos una vez, reusados por los 3 seeders)
│   ├── models/        modelos SnakeORM, un fichero por dominio
│   ├── selectors/     lecturas del dominio
│   ├── services/      escrituras y reglas del dominio
│   ├── usecases/      la operación completa de cada acción (escrita una vez)
│   ├── viewmodels/    la forma PLANA que lee una plantilla (dicts tipados, sin modelos)
│   ├── web/           nav.py: el catálogo del lateral, sin una sola URL dentro
│   ├── dto/           la forma que sale por JSON
│   ├── tests/         los tests del dominio (SQLite en memoria, sin servidor)
│   ├── auth.py        hash/verify de contraseñas (scrypt, solo stdlib)
│   └── config.py      lee el .env (raíz) y elige SQLite, PostgreSQL o MySQL
├── django/          demo Django  (SSR + API)
├── flask/           demo Flask   (SSR + API)
└── fastapi/         demo FastAPI (solo API)
```

**`viewmodels/` is the layer to understand**, because it was not there and its absence cost money. A
template that walks `post.author.username` is **loading a relationship in the presentation layer**,
where no `assert_queries` is looking: today it works because the selector did the `include`, and the
day somebody removes it the page keeps painting — with one query per row. The viewmodel navigates
the relationships and hands over already-formatted primitives, so the template cannot fire a query
even if it wanted to. And it makes the two sets of templates cheap along the way: if both read the
same flat shape, having two files costs the HTML and nothing more.

## Where the demos are heading

**This is going to grow, and on purpose.** The demos are not a pretty shop window: they are the only
place where the ORM gets exercised the way a real application would exercise it, with a server in
front, a real database and a user clicking. A unit test proves that a piece works; a demo proves it
works **when something uses it**.

And that is where the problem that justifies the work is: `frameworks/` touches **13 of the 24
`SnakeSession` methods** and **7** of the user-facing `SnakeQuery` API. That count is not written
here by hand —it would age— but held up by a test, `shared/tests/test_orm_api_coverage.py`, which
enumerates both APIs by introspection and keeps the list of what is NOT exercised along with the
reason. It fails in both directions: when a method gets covered, until it is struck off the list; and
when one that was already covered gets lost. **Tests do not count**, and that is deliberate: a
`session.savepoint()` dropped in so the method has a caller proves that the method exists, which was
never in doubt.

What nobody touches is not marginal:

- **the entire ASYNCHRONOUS session.** FastAPI *is* async and uses the synchronous one, so
  `AsyncSession`, `AsyncDriver`, the async pool and sync/async parity are only exercised by
  `src/test`, never by an app.
- **`for_update`** — the inventory stock reservation is the textbook case, and without a row lock it
  is a race. On top of that SQLite declares `ROW_LOCKING: Nope`, so it would exercise the degradation
  warning inside a real app.
- **`iterate()`** — streaming is where the memory failures live.
- **`savepoint()`**, **`set_isolation()`**, **`raw()`/`call()`**, **`recursive`**, the compound
  queries (`union`/`intersect`/`except_`), **`snake_trigger`**, **`snake_discriminator`**
  (polymorphism), **multi-database** and almost every migration operation (`RunPython`, `RunSQL`,
  `AlterColumn`…).

None of that gets exercised by a blog with fifteen posts. **A reasonably large application is
needed** —several navigable domains, listings that genuinely paginate, operations that happen inside
a transaction with steps that can fail— because those features only show up when something **has a
reason** to ask for them. A `savepoint` dropped in so it appears in the demo proves nothing; a
`savepoint` inside a multi-step operation that rolls back half of it does.

That is why the shell (`layout/base.html`) brought from the start more than the pages of the time
needed: named landmarks, skip to content, a notice region and a footer. **Adding that afterwards,
across twenty pages, is one of those jobs nobody does.** The sidebar went in for the same reason,
when there were still three sections.

The full plan, with its five phases and their gates, is in `docs/planning/frameworks/roadmap.md`.

What is NOT going to change: the two sets of templates stay two, the logic keeps living in
`shared/`, and each framework stays a wrapper.

### Templates carry no comments

Not one. If a template needs a paragraph to explain it, then logic has crept into it — and the logic
lives in Python, in `shared/viewmodels/` and `shared/usecases/`, which is where this repository
writes its reasons. The three `{# #}` blocks that were left went to the docstrings of
`apps/blog/urls.py` and `apps/lab/urls.py` (and their Django equivalents), which is where they
belong.

## Styles: Tailwind with components

One single CSS for the demos, in `shared/static/app.css`. **Node is needed to REBUILD it, never to
run a demo**: the built file is committed, so all three start with nothing but `uv` and work with no
network.

```bash
cd frameworks
npm install          # una vez
npm run build:css    # tras tocar shared/static/src/app.css
npm run watch:css    # mientras se maqueta
```

The source is `shared/static/src/app.css` and everything inside it is a **component**, not a loose
utility. A template writes `class="btn btn-primary"`, not fourteen utilities in a row: the day the
buttons change, they change there and not in twenty-seven files. Utilities are left for what shows up
once; what shows up twice earns a name.

Available vocabulary: `btn` (+ `btn-primary` / `btn-ghost` / `btn-danger`, `btn-sm` / `btn-md`),
`card` (+ `card-head` / `card-body` / `card-foot` / `card-title` / `card-sub`), `form` (+ `field` /
`label` / `input` / `textarea` / `select-inline` / `check`), `table-wrap` + `table` + `num`,
`dl` (field/value pairs of ONE record), `pager` + `pager-info`,
`alert` (+ `alert-ok` / `alert-error`), `badge` (+ `badge-ok` / `badge-muted`), `topbar` / `nav-link`
/ `layout` / `sidebar` (+ `sidebar-group` / `sidebar-title` / `sidebar-link` / `sidebar-blurb`) /
`page` / `stack`, `h1` / `lede` / `muted` / `code` / `empty`.

Two states are painted from the HTML and not from a class, because that way the screen reader finds
out just like the eye does: `.nav-link[aria-current="page"]` and
`.sidebar-link[aria-current="page"]` mark the current page, and `.btn[aria-disabled="true"]` dims the
edge of a pager. A template does NOT write `opacity-50`: it writes the attribute and the style
follows it.

The templates are TWO sets, one per framework, and that is on purpose: a template that names neither
Django nor Flask stops being the one a dev of either recognises as theirs, and these demos exist to
be read and copied.

## Configuration: `.env` at the ROOT of the repo

A **single `.env` at the root of the repository** configures the ORM AND the three demos — so the
connection is not repeated. Copy it from the template (`cp .env.example .env`; the tool does not
generate `.env` files, by permissions policy). **With no `.env`, the demos run against SQLite by
default.**

The demos **reuse the same `DB_*` connection as the ORM**; they only add an engine switch and one
database per framework:

```dotenv
# Conexión a Postgres (único servicio en Docker; ORM y demos corren en el host y conectan por el
# puerto publicado). La comparten el ORM y las demos. `DB_PORT` es la MISMA variable con la que
# docker-compose publica el contenedor, así que cambiarla aquí mueve las dos puntas a la vez; no se
# fija un número en la documentación porque entonces habría dos fuentes de verdad y una envejecería.
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=snakeorm_pass
DB_NAME=snakeorm_db

# Motor de las tres demos a la vez: sqlite (cero setup) | postgres (reusa DB_* de arriba).
DB_BACKEND=sqlite

# Una BD por framework cuando DB_BACKEND=postgres (se crean solas; host/user/... salen de DB_*).
DJANGO_DB_NAME=django_demo
FLASK_DB_NAME=flask_demo
FASTAPI_DB_NAME=fastapi_demo

# Clave para firmar las cookies de sesión del login. CÁMBIALA.
DEMO_SECRET_KEY=change-me
```

**Switching from SQLite to PostgreSQL (or back) is editing ONE line** (`DB_BACKEND`): all three demos
respect it. With `postgres`, each framework ends up in its own database (`django_demo`, `flask_demo`,
`fastapi_demo`) inside the same docker server, reusing the ORM's `DB_*` connection.

### When the tests run, those names are a BASE and not a name

One database per framework separates Django from Flask; what it does not separate is **one run from
another run of the same framework**, and several working sessions share a single server. Two suites
at once means one is rebuilding the schema the other is reading — and since the seeding is
deterministic, most of the time the counts come out the same and the run goes GREEN over a schema
that is no longer its own.

That is why, **when a suite is what starts things** (`make frameworks-test-*`, or `pytest` inside the
demo's folder), the name carries the session too: `flask_demo` becomes `flask_demo__s41287`, and on
SQLite the file becomes `flask__s41287.sqlite`. It comes from the PID, so **nothing has to be
exported**; the suite drops its database when it finishes, and whatever a run that blew up leaves
behind is collected by the sweep that `uv run pytest` starts with.

**Development servers do not carry it.** `make flask-dev`, `make seed` and a hand-typed `psql` see
exactly `flask_demo`, the database you seeded. The rule is `SNAKEORM_SESSION_ID`: if it is set, it is
appended, and if not, it is not. Set it by hand (`SNAKEORM_SESSION_ID=spike`) to pin a database
across several runs — with the caveat that a hand-written identifier is never swept, because only a
PID can be presumed dead.

## Getting started

```bash
uv sync --group test-frameworks   # instala django/flask/fastapi (una vez)

make django-dev      # http://127.0.0.1:8080  (SSR + API)
make flask-dev       # http://127.0.0.1:5000  (SSR + API)
make fastapi-dev     # http://127.0.0.1:8001  (solo API)

make frameworks-test # corre la verificación de las tres
```

Each folder has its own `README.md` with its routes/endpoints and what it demonstrates.
