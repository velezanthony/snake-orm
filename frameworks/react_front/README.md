# The React demo — the same domain, served by any of the three APIs

The same pages Django and Flask serve, drawn by a client that routes in the browser. It is not a
different app: it is a FOURTH presentation of the same domain, against the same `/api/` surface the
three Python demos already shared.

```bash
npm install
npm run dev          # http://localhost:5173
```

And with the API running, which is what this demo consumes:

```bash
cd ../django && uv run python manage.py runserver 8080     # :8080
```

## Switching API without touching a line

The topbar selector switches between **Django**, **Flask** and **FastAPI** on the fly. The whole
decision lives in `src/config/backends.ts` and nowhere else: the eleven services in
`src/domains/*/service.ts` ask for routes like `/api/orders` and never for a host.

The three come up like this, each on a port of its own so all three can be up at once — which is what the topbar switcher needs to be worth having:

```bash
cd django  && uv run python manage.py runserver 8080     # :8080
cd flask   && make flask-dev                             # :5000
cd fastapi && uv run uvicorn main:app --reload --port 8001
```

Switching backend **reloads the page**, and that is deliberate. Each API has its own session cookie,
so the logged-in user does not travel with you; and whatever rows were on screen belong to a database
the app no longer talks to. Leaving the tree mounted would mix fresh rows with stale ones with no way
to tell them apart.

## Why there is a proxy and not calls to the origin

The three demos authenticate with a signed session cookie, and all three mark it `HttpOnly`. That is
the right thing to do and it is exactly what a token in `localStorage` does not give you: the page's
script CANNOT read it, so an injected script cannot steal it.

The price is that a cross-origin `fetch` with `credentials: "include"` needs the server to answer with
the CORS credentials headers. None of the three send them, and teaching them to would mean
`SameSite=None` over http in development, which browsers reject.

So the dev server acts as a proxy: the browser only ever talks to Vite's origin, every cookie is
FIRST PARTY, and nothing on the Python side changes. Each backend hangs off its own prefix
—`/backend/django`, `/backend/flask`, `/backend/fastapi`— and the prefix is stripped on the way out.

### And the cookie jar is ISOLATED, not merely bounded

This was found by looking, not by reasoning: `/api/auth/me` was answering 401 right after a correct
login, and the request was carrying TWO cookies called `sessionid` — the one the proxy had set and
the one of a completely different application running on the same `localhost`.

`localhost` is a SHARED cookie namespace. Any project on the machine writes there, and `sessionid` is
what Django calls its session everywhere: it is not bad luck, it is the default outcome for anybody
with two Django projects. Narrowing the `Path` does not save you, because a cookie already set at
`Path=/` is sent to everything hanging below it.

That is why the proxy RENAMES (`vite.config.ts`): each backend's cookies are stored under a prefix of
their own, and on the way out only that prefix is forwarded, stripped. The three backends cannot see
each other —Flask and Starlette both call theirs `session`— and nothing else on `localhost` reaches
them.

## How it is put together

The tree goes **by domain**, mirroring `django/apps/` and `flask/apps/` instead of copying Angular:

| Folder | What is in it | Its Python equivalent |
|---------|---------|--------------------------|
| `src/domains/<d>/service.ts` | Talks to the API. Nobody else does `fetch` | `api.py` |
| `src/domains/<d>/types.ts` | What COMES BACK. What is sent goes in `service.ts` | the DTO |
| `src/domains/<d>/viewmodels.ts` | Hooks that compose the reads and flatten them | `viewmodels.py` |
| `src/domains/<d>/routes.tsx` | THAT domain's routes, with its prefix | `urls.py` |
| `src/domains/<d>/pages/` | They only paint | the templates |
| `src/core/` | `ui/` `http/` `hooks/` `lib/` `routing/` `layout/` | `nav.py`, `session.py`, `wire.py` |
| `src/config/` | `backends.ts`, the route registry and the root router | `config/settings.py` + `config/urls.py` |

The names go bare inside the domain —`service.ts`, not `orders.service.ts`— by the rule the repository
already applies to itself: inside `apps/orders/` the file is called `urls.py`, and inside
`shared/usecases/` it is called `orders_usecases.py`. **The name carries what the folder does not
say.**

The UI goes by atomic level, and each level has an alias of its own: `@atoms/Button`,
`@molecules/Card`, `@organisms/DataTable`. It is not about typing less — it is that the alias SAYS
which level a piece belongs to at the point of use. And the alias is the ONLY way to import it:
allowing `~/core/ui/atoms/Button` as well would be two names for one module.

**No `lazy` on the routes**, and it is a decision: splitting the bundle by route buys a smaller
initial download and pays for it with a spinner the first time you enter each section. This gets read
end to end on localhost, where the download is free and the spinner is the only thing you notice.

**The `ui/` components do NOT replace the CSS**: they wrap it. `shared/static/src/app.css` already did
the hard half with `@apply` —`.btn`, `.card`, `.badge` are components, not loose utilities—, and
writing `className="btn btn-primary btn-md"` in twenty places would throw that layer in the bin one
floor higher up. As a typed prop it is a closed set: `variant="primry"` does not draw an unstyled
button, it does not compile.

## The net that stops the catalogue from drifting

`shared/web/nav.py` says what sections there are and what pages hang off each one, without a single
URL. Each domain repeats it in its `routes.tsx` adding the client route, because React Router locates
a page by path and by nothing else. That is a FOURTH hand-written copy of a list this repo already
knows drifts, so there is a test that walks both and fails naming the section that moved:

```bash
cd ../.. && uv run pytest frameworks/shared/tests/test_the_react_catalogue_mirrors_the_nav.py -q
```

## A route is written once

`href("orders.detail", { orderId: 7 })` is the only way this client writes a URL. React Router ships
an `href()` that does the same thing and is no good here —it only exists in framework mode and this is
an SPA—, so it is built on top of the registry the domains already declare.

What it buys is five things that **do not compile**:

```ts
href("orders.detial", { orderId: 7 })       // nombre inexistente
href("orders.detail", { id: 7 })            // el parámetro se llama orderId
href("orders.list", { orderId: 7 })         // esa ruta no lleva parámetros
href("inventory.pair", { warehouseId: 1 })  // media clave compuesta no es una clave
href("orders.detail")                       // falta el objeto entero
```

Not one of them is catchable in a string template. `src/core/routing/routing.types.test.tsx` pins them
with `@ts-expect-error`, and the runner is `tsc`: if any of them starts compiling, the build goes red.
