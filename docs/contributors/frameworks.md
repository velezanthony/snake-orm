# Working on the demos

```bash
make frameworks-test          # the four suites: shared, FastAPI, Flask, Django
make typecheck-frameworks     # mypy over shared/ (from `frameworks/`, where `shared` resolves)
```

Both commands assume the repository is already set up: see [Development setup](development.md).

`frameworks/` holds **four presentations of ONE domain layer**, and the fourth is not Python:

| Demo | What it serves | Runs with |
|---|---|---|
| `frameworks/django/` | HTML pages **and** `/api/` JSON | `make django-dev` (:8080) |
| `frameworks/flask/` | HTML pages **and** `/api/` JSON | `make flask-dev` (:5000) |
| `frameworks/fastapi/` | `/api/` JSON only, over an `AsyncSession` | `make fastapi-dev` (:8001) |
| `frameworks/react_front/` | the same pages, drawn in the browser against any of the three APIs | `npm run dev` (:5173) |

They exist so that "how do I do this in my framework" has an answer you can read side by side —
which only works if they answer the same questions. Several tests exist to keep them honest, and
they are listed at the end.

**The React demo is a CLIENT, not a fifth domain**: it holds no query and no model, it calls the
same `/api/` surface, and its backend selector lives in `src/config/backends.ts` and nowhere else. It
is the reason the three APIs being identical stopped being a nicety — one client now depends on it.
It is NOT in `make frameworks-test`, which is a Python runner; what covers it from Python is
`test_the_react_catalogue_mirrors_the_nav.py`, and `npm run typecheck` covers the rest.

## The rule: a framework holds no logic

Everything a demo does lives in `frameworks/shared/`, once. The framework parses a request, calls
something in `shared/`, and renders the answer. If you find yourself writing a `filter()` inside a
view, it belongs one layer down.

| Layer | What lives there | Colour |
|---|---|---|
| `shared/models/` | the `@snake_model` classes, the whole graph | none |
| `shared/selectors/` | **fragments** that BUILD a `SnakeQuery` and do not run it, plus thin executors | fragments have none |
| `shared/services/` | the writes: `session.add`, `update`, `upsert`, `delete` | synchronous |
| `shared/usecases/` | validate, look up, decide, write, **commit once** | synchronous |
| `shared/aio/` | the asynchronous twin of `usecases/` | asynchronous |
| `shared/viewmodels/` | turns rows into what a template prints | synchronous |
| `shared/dto/` | turns rows into JSON-able dicts | none |
| `shared/web/` | `nav.py`: the sidebar sections the demos share | none |
| `shared/data/` | the seeder behind `make seed FW=… SCALE=…` | synchronous |
| `shared/migrations/` | the migration history, **once**, `<domain>/` per domain | none |
| `shared/static/` | the CSS and JS both SSR demos serve | none |
| `shared/auth.py` | password hashing and verification | none |

**The migrations live in `shared/` and each app SYMLINKS them.** `django/apps/orders/migrations`,
`flask/apps/orders/migrations` and `fastapi/apps/orders/migrations` are all links to
`shared/migrations/orders`, so the three demos replay the SAME history file by file. They used to be
three copies, which is a schema that can drift between demos built on one domain — and a drift a
`make frameworks-test` run would find only on whichever engine it happened to touch.

**A fragment has no colour and that is the whole seam.** Building SQL runs nothing, so a
`SnakeQuery` can be handed to either session. Write the query once as a fragment and both the
synchronous and the asynchronous path execute the same object — which is why their SQL is identical
by construction instead of by agreement.

```python
# shared/selectors/orders_selectors.py — a FRAGMENT: it builds, it does not run
def order_by_id(order_id: int) -> SnakeQuery[Order]:
    """FRAGMENT: one order by id, bare, NOT executed. What a WRITE path wants."""
    return SnakeQuery(Order).filter(Order.id == order_id)
```

What genuinely gets written twice is the control flow, because `await` is syntax and one function
body cannot serve both colours. That is the only duplication in the layer, and two nets hold the
copies together: `test_async_mirror.py` (same names, same parameters) and `test_sync_async_parity.py`
(same answer, same SQL, same message).

## Defining an endpoint

### The API: the VERB carries the action, the path names the resource

All three declare the method at the route.

```python
# FastAPI — apps/orders/urls.py
router = APIRouter(prefix="/api/orders", tags=["orders"])

@router.post("/{order_id}/reserve")
async def reserve(order_id: int, session: SessionDep) -> dict[str, object]:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK."""
    result = await usecases.reserve(session, order_id=order_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)
```

```python
# Flask — apps/orders/api.py
orders = Blueprint("orders-api", __name__, url_prefix="/api/orders")

@orders.post("/<int:order_id>/reserve")
def reserve(order_id: int) -> ResponseReturnValue:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK."""
    result = usecases.reserve(g.session, order_id=order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result))
```

```python
# Django — apps/orders/api.py, routed from apps/orders/urls.py
@api_view(["POST"])
def reserve(request: Request, order_id: int) -> Response:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK."""
    result = usecases.reserve(_session(request), order_id=order_id)
    return _refused(result) or Response(order_dict(result))
```

Three things are the same in all three and they are the convention:

- **The blueprint name carries `-api`** when the domain also has pages (`orders` versus
  `orders-api`), because two blueprints cannot share one `url_for` name.
- **A `Failure` becomes a status through `FAILURE_STATUS`**, never an ad-hoc number. That table is
  the single place `missing_fields` → 400, `not_found` → 404, `conflict` → 409 and
  `payment_declined` → 402 are decided.
- **Zero queries and zero `commit`** in the router. The use case owns the transaction.

**One URL resolves to one view in Django**, so a resource that answers two verbs is one view that
dispatches on the method — the collection GET+POST, the item GET+DELETE. What must not happen is one
URL per verb, because then `/api/orders` stops being the resource.

**Django's canonical collection ends in a slash.** `APPEND_SLASH` redirects a GET to it but REFUSES
to do so for a POST, and says why: a 301 cannot carry a body, so redirecting would silently drop the
order somebody just placed. Django raises instead of losing it. Flask and FastAPI serve
`/api/orders`; Django serves `/api/orders/`; the parity net compares operations, so one slash across
three routers is not drift.

### SSR: the PATH carries the action, the verb only says "show" or "do"

And this is not a style choice. **A browser `<form>` can emit GET and POST and nothing else** — no
PUT, no DELETE. So a deletion cannot be `DELETE /orders/<id>`; it is a path that says "delete":

```
GET  /orders/delete/<id>    the confirmation page
POST /orders/delete/<id>    performs it
```

Every page in both SSR demos follows that shape, and neither uses any verb but GET and POST.

```python
# Flask — the verb is declared where the route is
@orders.get("/update/<int:order_id>")
def edit_order_form(order_id: int) -> ResponseReturnValue: ...

@orders.post("/update/<int:order_id>")
def update_order(order_id: int) -> ResponseReturnValue: ...
```

```python
# Django — the route does not say the verb; the view does
path("update/<int:order_id>/", views.order_update, name="orders_update")

@require_POST
def order_update(request: HttpRequest, order_id: int) -> HttpResponse: ...
```

That asymmetry is each framework's convention rather than an inconsistency, and it has a
consequence worth knowing: the route reader in `shared/tests/routes.py` cannot get a verb out of a
Django urlconf, because it is not there.

**A page READS through a view model and WRITES through a use case.** The view model is what turns
rows into something a template can print, and it calls the use case underneath — so a page reaches
more operations than its view file appears to call.

## Authentication: neither `django.contrib.auth` nor `flask-login`

Both SSR demos do the same thing, and it is a decision rather than an omission:

```python
# The framework's signed cookie holds only the id...
session["user_id"] = user.id           # Flask
request.session["user_id"] = user.id   # Django

# ...and the USER comes from SnakeORM
current_user = selectors.get_user(orm_session, user_id)
```

`django.contrib.auth` requires Django's own `User` **model** and its migrations, so adopting it would
put a second ORM in a demo whose entire point is that SnakeORM owns the data. `flask-login` would
work over any ORM, but taking it would leave the two SSR demos asymmetric, since Django cannot follow
for the reason above.

So both use the lowest thing the two frameworks share natively — the signed session cookie — and
resolve the user through SnakeORM. Django sets `SESSION_ENGINE` to `signed_cookies` for the same
reason: the database-backed session table belongs to Django's ORM.

The API half is different and deliberately so: `auth.issue_token` and `auth.revoke_token` exist only
there, because a token is for a client with no cookie jar.

## The CSS: two node toolchains, and only one of them you need

There are two `package.json` in this tree and they share nothing:

| | what it is | when you need it |
|---|---|---|
| `frameworks/package.json` | the Tailwind CLI | only if you change the demos' styles |
| `frameworks/react_front/package.json` | Vite, TypeScript, ESLint | only if you work on the React client |

The two SSR demos need NEITHER to run. Django and Flask serve `shared/static/app.css` — FastAPI
is JSON only, so it never asks for it — and that file is
committed: node rebuilds it, it is never asked for at request time. That is deliberate — somebody
cloning this to read how an ORM drives three frameworks should not have to install a JavaScript
toolchain first.

```bash
cd frameworks
npm install          # once
npm run build:css    # after touching shared/static/src/app.css
```

**AND NOTHING WATCHES THE OUTPUT, which is the part to carry away.** `app.css` is build output living
in the index: edit the source, forget the rebuild, and both SSR demos serve the previous CSS while
every gate stays green. `make audit` does not build it and neither does CI, so the first thing that
notices is a screen looking wrong. Rebuild it in the same commit that changes the source, or the
change is not in the commit.

## The nets that will fail on you

None of these need a database or a running app; they read the demos' source with `ast`, because a
check that needs a framework to run is a check that gets skipped on the day it matters. The ORM's own
suite, and what its gates require, is in [Testing](testing.md).

| Net | What it holds |
|---|---|
| `test_the_demos_serve_the_same_routes.py` | Django's pages equal Flask's; the three APIs equal each other |
| `test_the_pages_and_the_api_do_the_same_things.py` | a WRITE reachable from one surface only is named, with its reason |
| `test_async_mirror.py` | a domain twinned in `shared/aio/` is twinned WHOLE |
| `test_sync_async_parity.py` | both colours give the same answer, SQL and warnings |
| `test_selectors_and_services.py` | every selector and service is exercised at least once |
| `test_the_page_and_the_api_reach_one_usecase.py` | INSIDE one demo, `/orders` and `/api/orders` come down on the same use case |
| `test_nav_is_wired_in_both_demos.py` | every sidebar section both demos can reverse into a link |
| `test_demo_templates_match.py` | the two SSR demos lay their templates out the same way, file for file |
| `test_the_react_catalogue_mirrors_the_nav.py` | the React sidebar says what `shared/web/nav.py` says |
| `test_the_session_says_what_the_engine_cannot_do.py` | the session announces every caveat the demo branches on |

The first two are the two AXES and the pair is the point: the three-column net compares frameworks
HORIZONTALLY, and three apps can drift the same way and still agree with each other. The one-use-case
net is the vertical axis — inside a single app, does the page decide what the endpoint decides? If it
does not, the demo has stopped being a BFF.

Two of them keep catalogues of exemptions — `_SSR_SPELLINGS`, `_NOT_A_DOMAIN_ENDPOINT` and `_OWED`
in the routes net, `_WRITE_ON_ONE_SURFACE` and `_API_ONLY` in the surfaces one — and each entry
carries **why**. Two kinds of reason live there and telling them apart
is the point: a DECISION, and a gap that is simply NOT AUDITED, which says so in those words. A
rationale you do not have is worse than none, because it closes the question. Every catalogue also
has a test that deletes an entry the day it stops applying.

## Adding a domain

1. Models in `shared/models/`, linked with `snake_link()`.
2. Its migrations in `shared/migrations/<domain>/`, and a **symlink** to that directory from each
   app's `apps/<domain>/migrations`. One history, three demos.
3. Fragments in `shared/selectors/` — build the query, do not run it.
4. Writes in `shared/services/`, orchestration in `shared/usecases/` with **one** commit.
5. If FastAPI is going to serve it, its twin in `shared/aio/` — **whole**, or the mirror net fails.
6. `shared/dto/` for JSON, `shared/viewmodels/` for templates.
7. The routers: `apps/<domain>/urls.py` in FastAPI, `apps/<domain>/api.py` in Flask and Django,
   `apps/<domain>/web_urls.py` for Django's pages and `apps/<domain>/urls.py` for Flask's.
8. Register: `include_router` in FastAPI's `main.py`, `register_blueprint` in Flask's `app.py`,
   `include()` in Django's `config/urls.py`.
9. The sidebar: a `NavSection` in `shared/web/nav.py:SECTIONS`, plus its route in
   `flask/apps/nav.py:ENDPOINTS` and `django/apps/nav.py:_URL_NAMES`. Miss it and
   `test_nav_is_wired_in_both_demos.py` goes red.
10. `make frameworks-test`, and read what the catalogues ask you to write down.
