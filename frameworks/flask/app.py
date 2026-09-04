from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import django_htmx  # noqa: E402
from flask import Blueprint, Flask  # noqa: E402
from flask_smorest import Api  # noqa: E402

# ▶ SnakeORM: the ROOT config (SnakeOrmConfig) + its connection (SnakeConnectionConfig)
from snakeorm.contrib import (  # noqa: E402
    SnakeDebugLanguage,
    SnakeDebugWSGI,
    SnakeOrmConfig,
)
from snakeorm.cli.hooks import flask_command  # noqa: E402

from apps.accounts.api import accounts as accounts_api_bp  # noqa: E402
from apps.accounts.urls import accounts as accounts_bp  # noqa: E402
from apps.auth.api import auth as auth_bp  # noqa: E402
from apps.auth.urls import auth_web as auth_web_bp  # noqa: E402
from apps.billing.api import billing as billing_api_bp  # noqa: E402
from apps.billing.urls import billing as billing_bp  # noqa: E402
from apps.blog.api import blp as api_blp  # noqa: E402
from apps.blog.urls import blog  # noqa: E402
from apps.content.api import content as content_api_bp  # noqa: E402
from apps.content.urls import content as content_bp  # noqa: E402
from apps.engagement.api import engagement as engagement_api_bp  # noqa: E402
from apps.engagement.urls import engagement as engagement_bp  # noqa: E402
from apps.lab.api import blp as lab_api_blp  # noqa: E402
from apps.lab.urls import lab  # noqa: E402
from apps.inventory.api import inventory as inventory_api_bp  # noqa: E402
from apps.inventory.urls import inventory as inventory_bp  # noqa: E402
from apps.logistics.api import logistics as logistics_api_bp  # noqa: E402
from apps.logistics.urls import logistics as logistics_bp  # noqa: E402
from apps.nav import inject_sidebar  # noqa: E402
from apps.orders.api import orders as orders_api_bp  # noqa: E402
from apps.orders.urls import orders as orders_bp  # noqa: E402
from apps.taxonomy.api import taxonomy as taxonomy_api_bp  # noqa: E402
from apps.taxonomy.urls import taxonomy as taxonomy_bp  # noqa: E402
from shared import config  # noqa: E402
from seed import seed  # noqa: E402

# ▶ SnakeORM: the connection comes from the shared config, which knows all THREE engines. This used
#   to be a two-branch `if` copy-pasted into every demo, and `DB_BACKEND=mysql` fell into the `else`:
#   the app talked to MySQL while the migrations were applied to a SQLite file.
_CONNECTION = config.connection_config("flask")

# ▶ SnakeORM: THE root config — connections (databases) + panel (debug, advise_ms, language) in ONE
#    object. Copy this into your app: it is everything SnakeORM needs, together and typed.
SNAKE = SnakeOrmConfig(
    databases={"default": _CONNECTION},
    # The `envelope` channel ships debug in the JSON of every response: no `?_debug=1`, no flag.
    debug=os.environ.get("SNAKE_ORM_DEBUG", "ssr,envelope,timing"),
    advise_ms=float(os.environ.get("SNAKE_ORM_ADVISE_MS", 10)),
    language=SnakeDebugLanguage.coerce(os.environ.get("SNAKE_ORM_LANG")),
    # ▶ SnakeORM: WHERE this runs. The channels above hand the SQL to whoever asks, so without it
    #   the middleware refuses to start instead of guessing.
    production=os.environ.get("SNAKE_ORM_PRODUCTION", "false").lower()
    in {"1", "true", "yes", "on"},
)


SECRET_KEY = os.environ.get("DEMO_SECRET_KEY", "snakeorm-flask-demo-secret")

_SMOREST_CONFIG = {
    "API_TITLE": "SnakeORM · Flask demo",
    "API_VERSION": "v1",
    "OPENAPI_VERSION": "3.0.3",
    "OPENAPI_URL_PREFIX": "/api",
    "OPENAPI_JSON_PATH": "openapi.json",
    "OPENAPI_SWAGGER_UI_PATH": "/docs",
    "OPENAPI_SWAGGER_UI_URL": "https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
}


# The htmx the lab's pager loads, served straight out of `django-htmx`. A Flask app reaching into a
# Django package reads oddly; the alternative reads worse — a second copy somebody has to keep at the
# Django demo's version. It is a Python dependency `uv sync` installs, so the demos boot with no
# network.
_HTMX = Blueprint(
    "vendor",
    __name__,
    static_folder=str(Path(django_htmx.__file__).parent / "static" / "django_htmx"),
    static_url_path="/vendor",
)


def create_app() -> Flask:
    # `static_folder` points at the CSS SHARED with Django (frameworks/shared/static).
    app = Flask(
        __name__,
        static_folder=str(_HERE.parent / "shared" / "static"),
        static_url_path="/static",
    )
    app.secret_key = SECRET_KEY
    app.config.update(_SMOREST_CONFIG)

    app.config["snakeorm"] = SNAKE  # ▶ SnakeORM: the hook opens it with `.open()`

    # ▶ SnakeORM: `flask snakeorm tables` beside `flask run`. The adapter carries no logic — it
    #   hands the arguments to the same core the `snakeorm` executable uses.
    app.cli.add_command(flask_command())

    if os.environ.get("SEED_ON_BOOT", "1") != "0":
        # ▶ SnakeORM: the schema is built by the per-domain MIGRATIONS. drop_all resets it
        #   (deterministic reseed), SNAKE.migrate() applies apps/*/migrations in dependency order.
        from shared import config

        config.drop_all("flask")
        SNAKE.migrate()
        seed()

    # SSR blueprints take the PLAIN name and the JSON side carries `-api`. Five of them had to take
    # that name back off an API blueprint that was holding it, which is why the convention is written
    # down rather than remembered.
    app.register_blueprint(_HTMX)
    app.register_blueprint(auth_web_bp)
    app.register_blueprint(blog)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(taxonomy_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(engagement_bp)
    app.register_blueprint(lab)

    # On the APP and not on a blueprint: the shell wraps every page there is, so a sidebar only some
    # blueprints could draw would render differently depending on who answered.
    app.context_processor(inject_sidebar)

    # ▶ SnakeORM: the WHOLE JSON API is registered on the `Api` so that EVERY endpoint shows up in
    #    the Swagger at `/api/docs`. They reuse the session the app-wide hook leaves in `g.session`.
    api = Api(app)
    api.register_blueprint(api_blp)  # blog: auth + post CRUD + statistics
    api.register_blueprint(lab_api_blp)  # the ORM lab, in JSON
    api.register_blueprint(accounts_api_bp)
    api.register_blueprint(inventory_api_bp)
    api.register_blueprint(auth_bp)
    api.register_blueprint(billing_api_bp)
    api.register_blueprint(content_api_bp)
    api.register_blueprint(engagement_api_bp)
    api.register_blueprint(orders_api_bp)
    api.register_blueprint(taxonomy_api_bp)
    api.register_blueprint(logistics_api_bp)

    # ▶ SnakeORM: the debug panel, with channels/threshold that COME FROM the root config itself.
    # Flask's WSGI (typeshed) types `start_response` with 3 args, ours with 2: an irreducible seam
    # between the two signatures, not a bug. ONE suppression, in pyright's dialect — mypy does not
    # read `frameworks/` at all, so a mypy ignore here would be addressed to nobody.
    #
    # ORDER MATTERS for the `otel` channel: in Flask the LAST assignment is the OUTERMOST one, the
    # opposite of Django's list. An OpenTelemetry wrapper goes AFTER this block so our spans hang off
    # the application's while its server span is still open. Backwards, nothing fails — the traces
    # just arrive detached. Verified in `src/test/contrib/test_otel_middleware_order.py`.
    app.wsgi_app = SnakeDebugWSGI(
        app.wsgi_app,  # pyright: ignore[reportArgumentType]
        channels=SNAKE.channels(),
        config=SNAKE.debug_config(),
    )
    # app.wsgi_app = OpenTelemetryMiddleware(app.wsgi_app)   # ← OTel goes HERE, wrapping ours
    return app


# `create_app()` is NOT called here on purpose. Flask's CLI finds the factory on its own, so nothing
# is lost — and importing this module stops REBUILDING the database. It used to: `SEED_ON_BOOT`
# defaults to on, so the import ran `drop_all` + `migrate` + `seed` on every `--reload` cycle, and
# again whenever any tool imported the module to look at the models.
if __name__ == "__main__":
    create_app().run(debug=True)
