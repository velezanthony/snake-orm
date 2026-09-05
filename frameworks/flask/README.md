# SnakeORM · Flask demo (SSR + JSON API)

A Flask app that mounts on top of **SnakeORM** the pages of six domains —`blog`, `inventory`,
`orders`, `billing`, `taxonomy` and `logistics`— plus the `lab`, and exposes all ten of the shared
domain over JSON. Everything that thinks lives in `frameworks/shared/`: this app is a **wrapper**. A
route parses the request, calls a use case with FLAT parameters —it never hands it the `request`—
and translates the result into a response.

The Django demo mounts the same pages and the FastAPI one the same JSON. They are three wrappers over
a single domain, and that is the entire demonstration.

## What it demonstrates

- **A shared base, zero duplication**: the 26 models, the selectors, the services, the use cases, the
  viewmodels and the sidebar catalogue live ONCE in `frameworks/shared/`. This app writes its
  `app.py`, its `seed.py`, its routes and its templates. Nothing else.
- **Thin views with an explicit failure map**: the use case returns a value or a `Failure`, and the
  view translates by `reason` (`missing_fields`/`taken`/`bad_credentials` → flash + redirect back to
  the form; `not_found`/`forbidden` → 404). The use case validates, orchestrates and does the
  `commit`.
- **Somebody else's post answers 404, not 403**, and both codes are in the same dictionary on
  purpose: a 403 CONFIRMS that the post exists, which is exactly the fact the asker had no right to
  know. Django already answered 404; Flask did not, so the same request got two different answers
  depending on who served it.
- **No N+1**: the listings use `include()` and the relationships are navigated in
  `shared/viewmodels/`, not in the template. Touching a relationship that was not included **raises**
  instead of firing SQL in silence.
- **The CSVs are written WHILE they are read**: `apps/exports.py` serves a `CsvExport` whose rows are
  a generator over `session.iterate()`. And there is a measured trap there: `stream_with_context` is
  NO good on Flask 3.1 —it pushes the contexts lazily, so `teardown_app_request` has already closed
  the session by the time the body starts pulling rows—, so the session is TAKEN OUT of `g` with
  `g.pop("session")` and the stream becomes its owner. With a `list()` in the view all of this comes
  out green and the page goes back to loading the whole table into memory before the first byte.
- **The `orders` operations declare their isolation level before reading**, and this app's
  `before_app_request` hook may already have spent the transaction before the handler starts.
  Postgres accepts the declaration silently when it would change nothing, so the failure is invisible
  on the machine where it is written and fatal on MySQL.
- **ORM debug in a hybrid app (SSR and API) in one line**:
  `app.wsgi_app = SnakeDebugWSGI(app.wsgi_app, channels=SNAKE.channels(), config=SNAKE.debug_config())`.
  The middleware branches on `Content-Type`: on HTML it injects the panel before `</body>` (the `ssr`
  channel); on JSON it adds the `snakeorm` block while the `envelope` channel is on, and **always**
  the `Server-Timing` header (the `timing` channel).

## SSR routes

**No trailing slash, and it is deliberate.** The Django demo mounts these same pages WITH a slash
because that is its convention; here there is none because a Flask dev would not write one either.
The two demos exist to be read and copied, so each one looks like what its own people would have
written.

Every domain repeats the SAME taxonomy of pages —`list`, `detail`, `create`, `update`, `delete`,
`report`, `export`— with the action written into the path instead of implied by the verb. Anyone who
has seen `/inventory/list` can guess `/orders/list` before opening it.

### Auth (`apps/auth/urls.py`)

| Method | Route | What it does |
|--------|------|----------|
| GET/POST | `/auth/register` | User signup (unique username/email, hashed password) and sign in. |
| GET/POST | `/auth/login` | `verify_password` and `user_id` into the signed cookie; honours `?next=`. |
| POST | `/auth/logout` | `session.clear()`. |

### Blog (`apps/blog/urls.py`) — the only pages behind a login

| Method | Route | What it does |
|--------|------|----------|
| GET | `/` | Redirects to the listing if there is a session, and to the login if not. |
| GET | `/posts` | Listing with the author loaded (`include` → a single query). |
| GET/POST | `/posts/new` | Create a post of your own. |
| GET | `/posts/<id>` | Detail with its author. |
| GET/POST | `/posts/<id>/edit` | Edit a post of your own; somebody else's or non-existent → 404. |
| GET/POST | `/posts/<id>/delete` | Confirmation and deletion; somebody else's or non-existent → 404. |

The `delete` has a confirmation page because a GET cannot delete anything: a bare link that did would
be one crawler away from emptying the blog.

### Inventory (`apps/inventory/urls.py`) — the key is a PAIR

The stock row is identified by `(warehouse_id, sku_id)`, so the key travels through the URL in two
halves, typed `<int:...>` so that a URL with a word in it is a 404 from the router and not a
`ValueError` from the view.

| Method | Route | What it does |
|--------|------|----------|
| GET | `/inventory/list` | Stock with `include` of warehouse and sku, `?warehouse=` filter and a pager. |
| GET | `/inventory/detail/<warehouse_id>/<sku_id>` | The whole pair, its two to-one relations flattened and its movements. |
| GET/POST | `/inventory/create` | Physical stocktake (UPSERT): the form picks the pair. |
| GET/POST | `/inventory/update/<warehouse_id>/<sku_id>` | Corrects the levels; the key's selects are `disabled`. |
| GET/POST | `/inventory/delete/<warehouse_id>/<sku_id>` | Confirmation; with history it answers 409 (FK RESTRICT). |
| GET | `/inventory/report` | Aggregates: `annotate`, `group_by`, `having` and a window function. |
| GET | `/inventory/export` | Streaming CSV of the movements; `?warehouse=` is OPTIONAL. |

The `export` carries no key in the path and its filter travels in the query string: it bounds HOW
MUCH the file brings, which is not the same as naming the row the route is about. A sidebar link
carries nothing, so it has to arrive at the whole file.

### Orders (`apps/orders/urls.py`) — the domain with operations

| Method | Route | What it does |
|--------|------|----------|
| GET | `/orders/list` | Listing with the customer and the warehouse flattened, filtered by state and paged. |
| GET | `/orders/detail/<id>` | The order with its lines. |
| GET/POST | `/orders/create` | Creating a draft order. |
| GET/POST | `/orders/update/<id>` | Editing the draft. |
| GET/POST | `/orders/delete/<id>` | Confirmation and deletion. |
| GET | `/orders/report` | Aggregates and a compound query (`UNION` with a per-branch `LIMIT`). |
| GET | `/orders/export` | Streaming CSV of the lines; `?state=` is optional. |
| GET | `/orders/operate` | The PICKER: the listing narrowed to the drafts you can operate on. |
| GET | `/orders/operate/<id>` | The operation's page. |
| POST | `/orders/operate/<id>/reserve` | Reserves the stock under a row lock (`for_update`). |
| POST | `/orders/operate/<id>/settle` | Issues the invoice and rewinds a failed charge to a `savepoint`. |
| POST | `/orders/operate/<id>/cancel` | Cancels and gives the stock back. |

**`operate` is two routes for one action, and the sidebar is the reason.** `shared/web/nav.py` puts
`operate` in the menu, and a sidebar link carries no id: so `/orders/operate` on its own has to
answer something useful by itself, and what it answers is the picker.

**The three operations are POST routes of their own**, not one route that branches on a button's
name. Each is a different transaction with a different failure map, and a single handler would have
to READ the form to know which — a read, right on the path where a read is the one thing that cannot
happen. On top of that the URL becomes the name of what happened, which is what a log line, a 405 and
a redirect all end up quoting. And a GET that reserved would be an operation a crawler, a prefetch or
the browser's back button could execute.

### Billing (`apps/billing/urls.py`) — three pages, and the missing ones are the argument

| Method | Route | What it does |
|--------|------|----------|
| GET | `/billing/list` | Invoices with THREE to-one hops flattened per row and without paying a query for any of them. |
| GET | `/billing/detail/<invoice_id>` | The invoice with its payments. |
| GET | `/billing/report` | What has been collected, what is outstanding and how it splits. |

There is no `create`, `update` or `delete`: an invoice is RAISED by the `settle` of orders and SETTLED
by `pay_invoice`, never by a form. A form that let you rewrite an amount would be a demonstration of
the one thing an accounting program cannot offer. `shared/tests/test_nav.py` asserts that absence, so
it is a decision the catalogue enforces and not a page nobody got around to writing.

### Lab (`apps/lab/urls.py`)

`/lab/list` · `/lab/aggregates` · `/lab/subqueries` · `/lab/joins` · `/lab/pagination` ·
`/lab/problems`

The entry page is called `list` and not `index`: the shared catalogue gives every section a `list`
page, so "every domain has a listing" is an invariant and not a rule with an exception inside it —
and an exception is where a sidebar link falls through. `problems` triggers an N+1 on purpose so the
debug panel points at it.

## JSON API

The whole API hangs off `/api/` by resource, on `flask-smorest`, and is registered on the same `Api`
object, so ALL the endpoints show up in the Swagger.

| Prefix | Module | What it exposes |
|---------|--------|------------|
| `/api/posts`, `/api/auth` | `apps/blog/api.py` | Post CRUD, `stats` and the signed-cookie session. |
| `/api/accounts` | `apps/accounts/api.py` | Roles and a user's roles. |
| `/api/auth` | `apps/auth/api.py` | A user's tokens and sessions. |
| `/api/billing` | `apps/billing/api.py` | Plans, subscriptions, invoices and payments. |
| `/api/content` | `apps/content/api.py` | A post's revisions and attachments. |
| `/api/engagement` | `apps/engagement/api.py` | Comments, reactions and views. |
| `/api/inventory` | `apps/inventory/api.py` | Warehouses, SKUs, stock, movements and reservation. |
| `/api/taxonomy` | `apps/taxonomy/api.py` | Groups, tags and a post's tags. |
| `/api/logistics` | `apps/logistics/api.py` | Depots, a delivery's sheet, the departures board and the load per slot. |
| `/api/lab` | `apps/lab/api.py` | The lab's same experiments, in JSON. |

`/api/docs` is the Swagger UI and `/api/openapi.json` the document. Each domain's page blueprint
carries the PLAIN name (`billing`) and its JSON one the `-api` suffix (`billing-api`): two blueprints
cannot share a `url_for` name, and two domains have already had to reclaim theirs from an API
blueprint that was occupying it.

## Authentication: no `flask-login`, and on purpose

The login puts `user_id` into Flask's `session` (the signed cookie) and the user comes out of
SnakeORM. `flask-login` is not used, and not out of ignorance: it would work on top of any ORM, but
the Django demo CANNOT follow it — `django.contrib.auth` requires Django's `User` model and its
migrations, that is to say a second ORM inside the demo.

So both SSR demos use the lowest thing both frameworks ship with, the signed session cookie, and that
is what keeps them symmetric. It is explained in full in
[Working on the demos](../../docs/contributors/frameworks.md).

## Structure

```
frameworks/flask/
├── app.py                  # app factory: SnakeOrmConfig, blueprints, seed on boot, debug WSGI
├── apps/
│   ├── <domain>/           # accounts auth billing blog content engagement inventory lab orders taxonomy
│   │   ├── urls.py         #   páginas SSR (Blueprint con url_prefix)
│   │   ├── api.py          #   API JSON (Blueprint de flask-smorest, prefijo /api/<domain>)
│   │   ├── models.py       #   re-export de los modelos compartidos
│   │   ├── selectors.py    #   re-export de las lecturas compartidas
│   │   ├── services.py     #   re-export de las escrituras compartidas
│   │   ├── usecases.py     #   re-export de los casos de uso compartidos
│   │   ├── viewmodels.py   #   re-export de la forma plana que lee la plantilla
│   │   └── migrations/     #   el esquema del dominio, que es lo que construye la BD
│   ├── exports.py          # el CSV en streaming, escrito una vez para los dominios que exportan
│   └── nav.py              # el catálogo compartido convertido en endpoints de Flask
├── templates/
│   ├── layout/             # base.html, _sidebar.html, error.html
│   └── <domain>/<action>/  # una carpeta por página de la taxonomía
├── seed.py                 # reset + migrate + siembra a la escala DEMO_SCALE
└── verify.py               # la verificación con app.test_client() (script y pytest)
```

A domain has TWO route files because it has TWO surfaces. `urls.py` is the pages and `api.py` the
JSON; putting both in one module would force `app.py`'s registration to choose which of the two
halves it wants, which is something it cannot do.

The CSS is **a single file shared with Django** (`frameworks/shared/static/app.css`, served under
`/static`), with a vocabulary of components instead of loose utilities. It is built with Tailwind but
it is committed: **Node is needed to rebuild it, never to run the demo**. The details are in
`frameworks/README.md`.

## Configuration and engine

The `.env` lives at the **root of the repository**, one single file for the ORM and the three demos.
`DB_BACKEND` picks `sqlite` (the default), `postgres` or `mysql`, and `FLASK_DB_NAME` gives this demo
its own database, which is created for you if it does not exist. With no `.env` it falls back to
SQLite (`frameworks/flask/flask.sqlite`).

An unknown `DB_BACKEND` **STOPS**, it does not fall back to SQLite: before, anything that was not
`postgres` ended up in a local file, so a `DB_BACKEND=postgress` with one `s` too many brought the
demo up against something else entirely and it all seemed to work. The "Configuration" section of
`frameworks/README.md` has the whole file.

**The schema is built by the per-domain MIGRATIONS**, not by an `init_schema`. On boot, `app.py` does
`config.drop_all("flask")`, `SNAKE.migrate()` —which applies `apps/*/migrations` in dependency order—
and seeds. `SEED_ON_BOOT=0` skips all three steps.

## Demo users

They are seeded by `shared/data/factory.py` as `demo1`, `demo2`, … (one per user in the scale). They
all share the same password, `test1234` (`DEMO_PASSWORD`, in the clear for the demo only; the seeder
hashes it ONCE and reuses the hash, salt included, so that seeding at the `massive` scale does not
take hours).

The volume is picked by `DEMO_SCALE`: `minimal`, `normal` (the default), `large` or `massive`. The
scale fixes the counts of the primary entities in `shared/data/scales.py` and the factory DERIVES the
rest with fixed ratios, so all of the volume goes up or down by moving one constant.

## How to run it

```bash
uv sync --group test-frameworks   # una vez

make flask-dev                    # http://127.0.0.1:5000
make flask-dev SCALE=massive      # lo mismo, con la escala de estrés
make seed FW=flask SCALE=large    # sembrar sin arrancar el servidor
```

Then, in the browser:

- `http://127.0.0.1:5000/auth/login` — sign in as `demo1` / `test1234`.
- `http://127.0.0.1:5000/posts` — SSR listing; at the bottom the **debug panel** appears with the SQL
  that page ran.
- `http://127.0.0.1:5000/api/posts` — JSON with the `snakeorm` block. Have a look at
  `Server-Timing`, which always travels.

> The `envelope` and `sidecar` channels expose SQL and parameters: in production they are turned off
> with `production=True` in the middleware. Here it is in development mode on purpose.

## Verification (without starting a server)

`verify.py` uses `app.test_client()` and is **36 tests**. Each one reseeds the database in an
`autouse` fixture, so they do not depend on the order.

It walks the blog's flow —register → login → create → list (`include` = 1 query, measured with
`assert_queries`) → edit → delete → logout— and on top of that checks what only the wrapper can
break:

- the `inventory` pages over the composite key, **reading the database back** with
  `config.make_session("flask")` and not just the HTML: that a page paints proves the template
  compiles; what a wrapper drops is the round trip, and a form that gives back half a composite key
  redirects to a plausible place just the same;
- the `orders` pages, including the three operations fired by POST — the row lock, the savepoint and
  the isolation level. That last one is checked by asking the session, from INSIDE the operation, for
  a level it does NOT already have: it is the only form of the error the engine complains about out
  loud;
- the `report` and `export` of the two domains that have them, plus the three `billing` pages;
- the `snake-debug-panel` in the SSR and the `snakeorm` block + `Server-Timing` in the API.

```bash
uv run pytest frameworks/flask/verify.py -q   # 36 passed
make frameworks-test-flask                    # lo mismo, desde el Makefile
make frameworks-test                          # las cuatro suites (shared + las tres demos)
```
