# SnakeORM · Django demo (SSR + JSON API)

**Django** demo app on top of **SnakeORM**, built on the shared domain of `frameworks/shared/`: ten
domains and 29 tables. Django here is ONLY the web layer; persistence, schema and migrations are
SnakeORM's job.

> **Django's ORM is not used** for the business data: there is no `models.Model`, no
> `makemigrations`, no Django tables. The models live in `frameworks/shared/models/` and are shared
> with the Flask and FastAPI demos. The **login session goes in a signed cookie**
> (`signed_cookies`): there is no session table in the database either.

## What it demonstrates

- **The same question answered by three frameworks.** The views are thin: they read the request, call
  a use case in `shared/` with flat parameters and translate the result into a response.
- **A template does not navigate a relationship.** Everything it paints comes from
  `shared/viewmodels/`, which returns flat dicts of primitives. A template walking
  `post.author.username` would be loading a relationship in the presentation layer, where no
  `assert_queries` is looking.
- **Somebody else's post answers 404, not 403**, just like in Flask. A 403 CONFIRMS that the post
  exists, which is exactly the fact the asker did not have.
- **The sidebar comes from a catalogue, not from a hand-written list.** `shared/web/nav.py` says what
  sections there are; `apps/nav.py` turns them into links with `reverse()`. The catalogue holds not a
  single URL: Django resolves by route name and Flask by endpoint, and a path written into the
  catalogue would be a third answer that nobody executes.

## Shared base (`frameworks/shared/`)

The app **does not redefine** models or data: it imports them. `frameworks/` is added to `sys.path`
(in `config/settings.py`, `manage.py` and `verify.py`).

| Import | What it brings |
|---|---|
| `from shared.models import ...` | The SnakeORM models of the ten domains (`snake_link()` already called there). |
| `from shared.data import seed, demo_scale` | The FACTORY seeder: the scale is set by `DEMO_SCALE`. |
| `from shared.viewmodels import ...` | The flat shape a template reads. |
| `from shared.usecases import ...` | The complete operation behind each action, written once. |
| `from shared import auth` | `hash_password` / `verify_password` (scrypt, stdlib only). |
| `from shared import config` | `make_session("django")`, `drop_all("django")`, `backend()`. |

**The `.env` lives at the ROOT of the repository**, one single file for the ORM and the three demos.
`DB_BACKEND` picks `sqlite` / `postgres` / `mysql`, and `DJANGO_DB_NAME` gives this demo its own
database.

## What is inside

| File | Role |
|---|---|
| `apps/<domain>/models.py`, `selectors.py`, `services.py`, `usecases.py`, `viewmodels.py` | Re-exports of `shared/`. The views import from THEIR layer, never from `shared` directly. |
| `apps/<domain>/web_urls.py` + `views.py` | The domain's SSR pages. |
| `apps/<domain>/urls.py` | The domain's JSON API (under `/api/`). |
| `apps/<domain>/migrations/` | The schema, per domain. Watched by `shared/tests/test_migration_drift.py`. |
| `apps/nav.py` | The sidebar's context processor: `(domain, action)` → route name. |
| `apps/exports.py` | The streaming CSV response, written once for inventory and orders. |
| `apps/blog/seed.py` | `drop_all` + per-domain migrations + seeding at the `DEMO_SCALE` scale. |
| `apps/blog/apps.py` | `ready()`: reset + seed on boot (idempotent by way of the reset). |
| `apps/blog/middleware.py` | `SnakeSessionMiddleware`: ONE SnakeORM session per request. |
| `apps/blog/guards.py` | Cookie auth: `current_user()` and the `login_required` decorator. |
| `templates/` | ONE tree for every page: `layout/`, and a directory per domain. |
| `apps/*/tests.py` | Verification with `django.test.Client`, without starting a server. |
| `verify.py` | Runs the whole of `apps`. It used to run only `apps.blog`, and the other domains' suites existed without ever executing. |

## SSR routes

Django keeps the trailing slash on all its routes; Flask does not add it. It is a deliberate
difference between the two demos, not an inconsistency.

### Auth (`apps/auth/web_urls.py`)

| Method | Route | What it does |
|---|---|---|
| GET/POST | `/auth/register/` | User signup (unique username/email, hashed password). |
| GET/POST | `/auth/login/` | Sign in: `verify_password` and stores `user_id` in the signed cookie. |
| POST | `/auth/logout/` | Clears the session. |

### Blog (`apps/blog/urls.py`) — the only pages behind a login

| Method | Route | What it does |
|---|---|---|
| GET | `/` | List of posts with their author (`include` → 1 JOIN, no N+1). |
| GET/POST | `/posts/new/` | Creates a post (`author_id` = the logged-in user). |
| GET | `/posts/<id>/` | A post's detail. |
| GET/POST | `/posts/<id>/edit/` | Edits a post. **Author only** (otherwise, 404). |
| GET/POST | `/posts/<id>/delete/` | Deletes a post. **Author only** (otherwise, 404). |

### Inventory (`apps/inventory/web_urls.py`) — the key is a PAIR

Stock is identified by `(warehouse_id, sku_id)`, so the key travels through the URL in two halves.
These pages do NOT ask for a login: stock has no owner, and a gate there would not be guarding
anything.

| Method | Route | What it does |
|---|---|---|
| GET | `/inventory/list/` | Stock with `include` of warehouse and sku, `?warehouse=` filter and a real pager. |
| GET | `/inventory/detail/<warehouse_id>/<sku_id>/` | The pair, its two to-one relations flattened and its movements. |
| GET/POST | `/inventory/create/` | Physical stocktake (UPSERT): the form picks the pair. |
| GET/POST | `/inventory/update/<warehouse_id>/<sku_id>/` | Corrects the levels; the key's two selects are `disabled`. |
| GET/POST | `/inventory/delete/<warehouse_id>/<sku_id>/` | Confirmation; with history it answers 409 and explains why. |
| GET | `/inventory/report/` | `annotate`, `GROUP BY` + `HAVING`, a window function and a `join` + `distinct`. |
| GET | `/inventory/export/` | **Streaming** CSV with `session.iterate()`. |

### Orders (`apps/orders/web_urls.py`) — the domain with operations

| Method | Route | What it does |
|---|---|---|
| GET | `/orders/list/` | Paginated orders, filtered by state. |
| GET | `/orders/detail/<id>/` | The order, its lines and its invoice if it has one. |
| GET/POST | `/orders/create/`, `/orders/update/<id>/`, `/orders/delete/<id>/` | The CRUD. |
| GET | `/orders/report/` | Aggregates, a window and a `union` with a per-branch `LIMIT`. |
| GET | `/orders/export/` | Streaming CSV of the lines. |
| GET | `/orders/operate/` | The picker: the orders you can operate on. |
| GET | `/orders/operate/<id>/` | What stock there is for each line, and which operation is offered. |
| POST | `/orders/operate/<id>/reserve/` | Locks the stock rows with `for_update` and promises the units. |
| POST | `/orders/operate/<id>/settle/` | Invoices, charges and ships; if the charge falls over, a `savepoint` rewinds without losing the invoice. |
| POST | `/orders/operate/<id>/cancel/` | Returns the units if they were reserved. |

> **The three operations declare their isolation level**, and `SET TRANSACTION` is only valid as the
> FIRST statement of the transaction. That is why their handlers read NOTHING before calling: they
> do `session.rollback()` right before, with the reason written next to it. Removing it breaks
> nothing on Postgres —the default level matches the one the operation asks for, so it is accepted
> silently— and is fatal on MySQL, which comes in `REPEATABLE READ`.

### Billing (`apps/billing/web_urls.py`)

| Method | Route | What it does |
|---|---|---|
| GET | `/billing/list/` | Paginated invoices, filtered paid/open. |
| GET | `/billing/detail/<invoice_id>/` | The invoice, its payments and what is left to collect. |
| GET | `/billing/report/` | `annotate`, and `GROUP BY` + `HAVING` over WHOLE cents. |

It has no `create`/`update`/`delete`, and that is design: an invoice is not edited by hand.
`shared/tests/test_nav.py` asserts that absence.

### Lab (`apps/lab/urls.py`)

`/lab/`, `/lab/aggregates`, `/lab/subqueries`, `/lab/joins`, `/lab/pagination`, `/lab/problems`.
The last one triggers an N+1 on purpose so the panel points at it.

## JSON API

Nine domains under `/api/`, plus the OpenAPI schema at `/api/schema/` and Swagger at `/api/docs/`.

```bash
curl 'http://127.0.0.1:8080/api/posts/' | jq .snakeorm          # bloque de debug en el JSON
curl -i 'http://127.0.0.1:8080/api/posts/'                      # cabecera Server-Timing
```

## Authentication: no `django.contrib.auth`, and on purpose

The login puts `user_id` into the signed cookie (`SESSION_ENGINE = signed_cookies`) and the user
comes out of SnakeORM. `django.contrib.auth` is NOT in `INSTALLED_APPS` and there is no
`AuthenticationMiddleware`.

It is not an oversight: `contrib.auth` requires Django's `User` **model** and its migrations, so
adopting it would put a SECOND ORM inside a demo whose entire point is that the data belongs to
SnakeORM. The same goes for the database session table, and that is why the session travels in a
signed cookie.

The Flask demo does exactly the same thing with Flask's `session` and without `flask-login`, which is
what keeps the two SSR demos symmetric. It is explained in full in
[Working on the demos](../../docs/contributors/frameworks.md).

## One session per request

`SnakeSessionMiddleware` (the innermost one) opens `config.make_session("django")` at the start of
every request, hangs it on `request.snake_session`, and on the way out **commits** (or **rolls back**
if the view raised) and **closes**. It sits INSIDE the capture scope of `SnakeDebugMiddleware`, so its
SQL shows up in the panel.

**The export is the exception, and it has to be**: the middleware closes the session when the view
returns, and a streaming body is produced AFTERWARDS. So `apps/exports.py` opens its OWN session and
closes it in the generator's `finally`. A generator reading from a closed session is the classic
failure of streaming exports.

## ORM debug

`SnakeDebugMiddleware` (the outermost of `MIDDLEWARE`) captures each request's SQL and delivers it
according to `SNAKE_ORM_DEBUG`, set in `settings.py` to **`ssr,envelope,timing`**:

- **`ssr`** — on the SSR pages, injects the HTML panel before `</body>`.
- **`envelope`** — under `/api/`, adds the `snakeorm` block to every JSON response while the channel
  is on, with no query param and no header. Take the channel away and the response goes out clean.
- **`timing`** — `Server-Timing` header (W3C) on every response.

> **Security — never in production.** `envelope`/`sidecar` expose SQL and parameters. The gate turns
> them off when `settings.DEBUG` is `False`. The test runner forces `DEBUG=False`, so the suites
> restore `DEBUG=True` with `override_settings` in order to exercise the envelope.

## How to run it

From `frameworks/django/`:

```bash
uv run python manage.py test apps    # verificación, sin levantar servidor
uv run python manage.py runserver 8080    # http://127.0.0.1:8080
```

On boot, `ready()` recreates the schema and seeds at the `DEMO_SCALE` scale (`normal` by default;
`minimal` speeds the boot up, `large`/`massive` put it under strain). The seeded users are `demo1`,
`demo2`, ... and **they all share the password `test1234`**.

## What the suites verify

`apps/blog/tests.py`, `apps/inventory/tests.py`, `apps/orders/tests.py` and `apps/billing/tests.py`,
with `django.test.Client` and no server:

- **The blog's full flow**: register → login → create → list (`include` = 1 query, measured with
  `snakeorm.debug.assert_queries`) → edit → delete → logout.
- **Isolation by author**: a user cannot edit or delete another's posts (404).
- **Composite key**: the five inventory pages, with the pair in the URL.
- **The orders operations reach the database**: reserving raises the held units on the real stock
  row, settling leaves the order in `SETTLED`, cancelling gives them back.
- **The export really streams**: four chunks of the body are read and the driver is checked to have
  consumed three rows, not the three hundred and twenty. The viewmodel's tests do not see that: they
  only look at the viewmodel, and a `list()` in the view would leave every one of them green.
- **The sidebar shows up on every page** and marks the current one with `aria-current`.
- **Debug**: the panel is injected in the SSR, the envelope travels in the JSON and `Server-Timing`
  is always there.
