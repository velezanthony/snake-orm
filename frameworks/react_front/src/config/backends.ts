/**
 * WHICH API this client is talking to. One file, and every request in the app goes through it.
 *
 * The three Python demos serve the SAME domain behind the SAME BFF surface — `/api/<resource>` —
 * which is the whole reason this fourth demo can exist at all. What they do NOT share is the origin
 * they answer on, and Django does not share the trailing slash either. Those two differences are the
 * entire delta, so they are written down HERE, once, instead of leaking into eleven services.
 *
 * ---------------------------------------------------------------------------------------------
 * THE COOKIE IS WHY THIS GOES THROUGH A PROXY AND NOT STRAIGHT AT THE ORIGIN.
 *
 * All three demos authenticate with a signed session cookie, and all three mark it `HttpOnly` —
 * Django's `sessionid`, Flask's `session`, Starlette's `session`. That is the right call and it is
 * the one thing a token in `localStorage` cannot give you: script on the page CANNOT read it, so an
 * injected script cannot steal it. The cost is that the browser only sends it back under the rules
 * of the origin that set it, and a cross-origin `fetch` with `credentials: "include"` needs the
 * server to answer with CORS credentials headers. None of the three sends them, and teaching all
 * three to would mean `SameSite=None` over plain http in development, which browsers refuse.
 *
 * So the dev server proxies instead. The browser only ever talks to the Vite origin, every cookie is
 * FIRST-PARTY, and nothing on the Python side has to change. `vite.config.ts` also rewrites each
 * cookie's `Path` to the backend's own prefix, which is what stops Flask's `session` and Starlette's
 * `session` — the same name, twice — from overwriting each other in one cookie jar.
 *
 * Behind a real deployment the same three prefixes are a reverse-proxy rule, and `mode: "direct"`
 * is there for the day one of them lives on its own origin with CORS configured.
 */

/** The three Python demos, by the name their folder uses. */
export type BackendId = "django" | "flask" | "fastapi";

export interface BackendConfig {
  readonly id: BackendId;
  /** What the switcher in the topbar shows. */
  readonly label: string;
  /** Where the app itself runs, for the "open the SSR original" link. */
  readonly origin: string;
  /** The path prefix the dev proxy forwards to `origin`. Also the cookie `Path`. */
  readonly prefix: string;
  /** Rewrites an API path into the one THIS backend actually registered. */
  readonly rewrite: (path: string) => string;
  /** The SSR route that mirrors a given API resource, for the "same page, rendered by them" link. */
  readonly page: (path: string) => string;
}

/**
 * Django's blog and auth routes carry a trailing slash and the other nine domains do not.
 *
 * That is not an inconsistency somebody should tidy up: `apps/blog/urls.py` was written when the
 * demo was a blog and Django's own convention is the slash, while every `apps/<domain>/urls.py`
 * added later mirrors Flask and FastAPI exactly. Django's `APPEND_SLASH` does not rescue a client
 * from the difference either — it redirects a GET and REFUSES to redirect a POST, because a 301
 * would drop the body.
 *
 * So the client states the rule instead of guessing it, and states it in the one place a rule about
 * an API belongs.
 */
/** Whole trees of Django routes that carry the slash: the blog's, and the auth surface on top of it. */
const DJANGO_SLASHED_TREES = ["/api/posts", "/api/auth", "/api/schema", "/api/docs"];

/**
 * Domains whose INDEX carries a slash and whose children do not.
 *
 * `path("api/orders/", include(...))` with a `path("")` inside means the list lives at
 * `/api/orders/` while the detail lives at `/api/orders/5` — bare. Django answers the bare index
 * with a 301, which a GET follows and a POST cannot: the redirect would drop the body. So the two
 * indexes get their slash here and nothing else does.
 */
const DJANGO_SLASHED_INDEXES = ["/api/orders", "/api/lab"];

function appendSlashForDjango(path: string): string {
  const [route = "", query] = path.split("?");
  const needsSlash =
    !route.endsWith("/") &&
    (DJANGO_SLASHED_TREES.some((p) => route === p || route.startsWith(`${p}/`)) ||
      DJANGO_SLASHED_INDEXES.includes(route));
  const rewritten = needsSlash ? `${route}/` : route;
  return query === undefined ? rewritten : `${rewritten}?${query}`;
}

export const BACKENDS: Readonly<Record<BackendId, BackendConfig>> = {
  django: {
    id: "django",
    label: "Django",
    origin: "http://127.0.0.1:8080",
    prefix: "/backend/django",
    rewrite: appendSlashForDjango,
    // Django mounts the SSR pages at the root and the JSON under `/api/`, so the mirror of
    // `/api/orders` is `/orders/list/`. The list page is the only one worth linking blind.
    page: (path) => appendSlashForDjango(path.replace(/^\/api/, "")),
  },
  flask: {
    id: "flask",
    label: "Flask",
    origin: "http://127.0.0.1:5000",
    prefix: "/backend/flask",
    rewrite: (path) => path,
    page: (path) => path.replace(/^\/api/, ""),
  },
  fastapi: {
    id: "fastapi",
    label: "FastAPI",
    // 8001 and not 8000, and 8000 is nobody's here. It is uvicorn's default AND Django's, so the
    // two demos used to fight over it and only one could be up — which defeats the switcher in the
    // topbar, whose whole point is changing backend without restarting anything. The `Makefile`
    // gives each one its own (`FASTAPI_PORT`, `DJANGO_PORT`) and these three lines are the other
    // half of that agreement; `shared/tests/test_the_ports_agree.py` holds the two halves together.
    origin: "http://127.0.0.1:8001",
    prefix: "/backend/fastapi",
    rewrite: (path) => path,
    // FastAPI has NO templates: it is the API-only demo. There is no SSR page to mirror, and the
    // interactive docs are the honest thing to open instead.
    page: () => "/docs",
  },
} as const;

export const BACKEND_IDS = Object.keys(BACKENDS) as readonly BackendId[];

const STORAGE_KEY = "snakeorm.backend";

function isBackendId(value: unknown): value is BackendId {
  return typeof value === "string" && value in BACKENDS;
}

/**
 * The backend a fresh browser starts on. `VITE_BACKEND=flask npm run dev` moves the default.
 *
 * Read through a guard because THIS MODULE IS ALSO IMPORTED BY `vite.config.ts` — on purpose, so
 * the proxy and the client cannot disagree about the prefixes. That import runs in Node, where
 * `import.meta.env` does not exist, and a bare read there takes the whole dev server down before it
 * has printed a line.
 */
function envBackend(): BackendId | null {
  const env = typeof import.meta === "object" ? (import.meta as { env?: Record<string, unknown> }).env : undefined;
  const value = env?.["VITE_BACKEND"];
  return isBackendId(value) ? value : null;
}

const DEFAULT_BACKEND: BackendId = envBackend() ?? "django";

/**
 * The backend in force right now.
 *
 * It is read from `localStorage` on every call rather than cached in a module variable, because the
 * value has to survive a reload — the switch below performs one on purpose.
 */
export function currentBackend(): BackendConfig {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isBackendId(stored)) return BACKENDS[stored];
  } catch {
    // A browser with storage denied (private mode, a locked-down profile) is not a broken app: it
    // is an app that cannot REMEMBER the choice. Falling through to the default is the whole fix.
  }
  return BACKENDS[DEFAULT_BACKEND];
}

/**
 * Points the app at another backend, and RELOADS.
 *
 * The reload is deliberate and it is not laziness. Every backend has a session cookie of its own, so
 * the logged-in user does not come with you — and neither does a single row already on screen, which
 * belongs to a database this app is no longer talking to. Swapping the base URL under a mounted tree
 * would leave stale rows next to fresh ones with no way to tell which is which. Starting again is
 * the only state that is honest about what just happened.
 */
export function switchBackend(id: BackendId): void {
  window.localStorage.setItem(STORAGE_KEY, id);
  window.location.assign("/");
}

/** The absolute URL for an API path on the backend in force. */
export function apiUrl(path: string): string {
  const backend = currentBackend();
  return `${backend.prefix}${backend.rewrite(path)}`;
}
