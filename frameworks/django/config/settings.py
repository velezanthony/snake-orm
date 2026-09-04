from __future__ import annotations

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from snakeorm.contrib.django import (  # ▶ SnakeORM: they type its constants (IntelliSense)
    SnakeOrmDatabase,
    SnakeOrmSettings,
)

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(
    0, str(BASE_DIR.parent)
)  # ▶ SnakeORM: access to the `shared` package (domain)
load_dotenv(BASE_DIR.parent.parent / ".env")

# ▶ SnakeORM: the session a test run belongs to, so `manage.py test` gets a database of its own and
#   `manage.py runserver` keeps the one you seeded. It has to be imported HERE, after the path
#   insert above, and it is `shared.session` and not `shared.config` on purpose: this file runs
#   before `django.setup()`, and `shared.config` would drag the whole domain graph and the ORM into
#   Django's settings import. `shared.session` imports `os` and `re`.
from shared.session import current as _snake_session  # noqa: E402
from shared.session import scoped as _snake_scoped  # noqa: E402

# ▶ SnakeORM: PANEL config (typed constant, read from the .env). SnakeDebugMiddleware reads it.
SNAKEORM: SnakeOrmSettings = {
    # `envelope` among the channels = the debug rides in every JSON response (no separate flag needed).
    "DEBUG": os.environ.get("SNAKE_ORM_DEBUG", "ssr,envelope,timing"),
    "ADVISE_MS": float(os.environ.get("SNAKE_ORM_ADVISE_MS", 10)),
    "LANG": os.environ.get("SNAKE_ORM_LANG", "en"),  # language the panel OPENS with
}

SECRET_KEY = os.environ.get(
    "DEMO_SECRET_KEY",
    "django-insecure-hnbi*!w4lde(6b%*m*ku&ww6gu=g&uwfsi2swk8ihaihwkuc^u",
)

DEBUG = True

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    # For `{% htmx_script %}` alone: the tag serves the htmx the package vendors, and the Flask demo
    # serves that same file so the two demos cannot end up on different versions.
    "django_htmx",
    "rest_framework",
    "drf_spectacular",
    "apps.blog.apps.BlogConfig",
]

# ORDER MATTERS, and the `otel` channel is the reason it matters SILENTLY. In Django the FIRST
# entry is the OUTERMOST one, so an OpenTelemetry middleware has to go ABOVE this line: our spans
# hang off the application's only if its server span is still OPEN when we deliver the report, and
# the outer middleware closes last. Put ours on top of OTel's and nothing fails — the traces simply
# arrive detached, and a suite that only checks "a trace arrived" stays green through it. Verified
# over the real Django in `src/test/contrib/test_otel_middleware_order_django.py`.
MIDDLEWARE = [
    # "opentelemetry.instrumentation.django.middleware.OpenTelemetryMiddleware",  # ← OTel goes HERE
    "snakeorm.contrib.django.SnakeDebugMiddleware",  # ▶ SnakeORM: SQL capture (the outermost one)
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",  # puts `request.htmx` there; the lab's pager reads it
    "apps.blog.middleware.SnakeSessionMiddleware",  # ▶ SnakeORM: session per request (the innermost one)
]

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "SnakeORM · Django demo",
    "VERSION": "v1",
    "SERVE_INCLUDE_SCHEMA": False,
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                # The sidebar of sections, on EVERY template. Wired here and not passed by each view
                # because a view that forgets it renders a page with no navigation and a 200 status.
                "apps.nav.sidebar",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def _require(key: str) -> str:
    try:
        return os.environ[key]
    except KeyError:
        raise ImproperlyConfigured(
            f"DB_BACKEND=postgres requires the environment variable {key} (sin default)."
        ) from None


# ▶ SnakeORM: connection source read from the .env (Django format → both Django AND the translator read it).
DATABASES: dict[str, SnakeOrmDatabase]
_BACKEND = os.environ.get("DB_BACKEND", "sqlite").strip().lower()
if _BACKEND == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": _require("DB_HOST"),
            "PORT": _require("DB_PORT"),
            "USER": _require("DB_USER"),
            "PASSWORD": _require("DB_PASSWORD"),
            # ▶ SnakeORM: the SAME rule `shared.config._pg_dbname` applies to the SAME variable, so
            #   Django and the ORM agree on which database this run is talking to. Under
            #   `manage.py test` that is `django_demo__s<pid>`; under `runserver`, `django_demo`.
            "NAME": _snake_scoped(_require("DJANGO_DB_NAME"), _snake_session()),
        }
    }
elif _BACKEND == "mysql":
    # Django demands `mysqlclient` for its MySQL backend, and this project already ships PyMySQL (the
    # driver SnakeORM uses). `install_as_MySQLdb()` is PyMySQL's official way of passing itself off as
    # it, and here that is more than enough: the demo does NOT use Django's ORM —its sessions ride in a
    # signed cookie and there are no models of its own—, so Django only needs the backend to load.
    #
    # Adding `mysqlclient` would have meant dragging a natively compiled dependency into a demo that is
    # not going to run a single query through it.
    import pymysql

    pymysql.install_as_MySQLdb()

    # ▶ SnakeORM: the third engine. It is written in Django format, just like the other two, because
    #   the `contrib.django` translator reads it — which is that piece's whole argument: your
    #   `DATABASES` does not change because you use SnakeORM. The pieces come from `MYSQL_*`, the same
    #   names the ORM's e2e tests use, so as not to invent a third set of variables.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.environ.get("MYSQL_PORT", "3306"),
            "USER": os.environ.get("MYSQL_USER", "root"),
            "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
            "NAME": _snake_scoped(
                os.environ.get("DJANGO_DB_NAME", "django_demo"), _snake_session()
            ),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # ▶ SnakeORM: the same file `shared.config` seeds (django_session and the seed → SAME DB).
            #   Which is why the session id goes here too: `_sqlite_path` puts it in the filename, and
            #   a Django writing to `django.sqlite` while the seed filled `django__s41287.sqlite`
            #   would be two halves each working perfectly and doing nothing together.
            "NAME": str(
                BASE_DIR / f"{_snake_scoped('django', _snake_session())}.sqlite"
            ),
        }
    }

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# The demo's CSS lives in frameworks/shared/static (SHARED with Flask); runserver serves it in dev.
STATICFILES_DIRS = [BASE_DIR.parent / "shared" / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
