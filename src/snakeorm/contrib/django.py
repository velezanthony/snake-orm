"""Django adapter: middleware that branches by `Content-Type` (the panel in HTML, `snakeorm` in JSON) for the hybrid SSR + `/api/` case.

The production gate is tied to `settings.DEBUG`. Django is imported LAZILY (only when serving the sidecar), so the module imports and tests without Django installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from snakeorm.advisor import DEFAULT_MIN_MS

# `X as X`: an EXPLICIT re-export — the user's settings.py imports them from here (Django's world).
from snakeorm.contrib.config import SnakeOrmDatabase as SnakeOrmDatabase
from snakeorm.contrib.config import SnakeOrmSettings as SnakeOrmSettings
from snakeorm.contrib.config import (
    SnakeOrmConfig,
    connection_from_mapping,
    debug_config_from_mapping,
)
from snakeorm.contrib.deliver import (
    allowed_channels,
    index_advice,
    plan_delivery,
    serve_sidecar,
    transform_body,
)
from snakeorm.contrib.sidecar import SidecarBuffer, new_token
from snakeorm.debug import (
    SnakeDebugChannel,
    SnakeDebugConfig,
    SnakeDebugLanguage,
    SnakeWebFramework,
    capture_queries,
    channels_from_env,
    export_report,
    RequestInfo,
    warn_unimplemented,
    warn_unsupported,
)

if TYPE_CHECKING:
    from snakeorm.session import SnakeSession

_SIDECAR_PREFIX = "/__snake__/"


def _django_is_production() -> bool:
    """`True` if Django says it is NOT in debug; `False` if Django is absent (falls back to dev).

    It only resolves the `settings.DEBUG` signal; the real gate is exercised by the pure layer
    `allowed_channels`.
    """
    try:
        from django.conf import settings  # pyright: ignore[reportMissingImports]

        return not settings.DEBUG
    except Exception:
        return False


def _csp_nonce_for(request: Any, config: SnakeDebugConfig) -> str | None:
    """The REQUEST's nonce (`request.csp_nonce`) if there is one; otherwise the config's.

    django-csp mints one per response and hangs it there, which is what CSP asks for; a nonce fixed
    in the config is the same for every response. Django is the only one of the three adapters with
    a request object to ask. Absent django-csp the attribute is not there and the config wins.
    `str()` because the value is a lazy object, not a `str`.
    """
    nonce = getattr(request, "csp_nonce", None)
    return config.csp_nonce if nonce is None else str(nonce)


def _accept_of(request: Any) -> str:
    """The request's `Accept` header, or an empty string when there is none to read.

    `request.headers` is Django's own case-insensitive mapping. It is read defensively because this
    method also runs against request doubles that carry nothing but a path.
    """
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    return str(headers.get("Accept", ""))


class SnakeDebugMiddleware:
    """Django middleware that captures the SQL and delivers the debug per `SNAKE_ORM_DEBUG`."""

    def __init__(self, get_response: Any) -> None:
        self._get_response = get_response
        # The config comes out of the `SNAKEORM` constant of settings.py (Django's idiomatic way).
        # If it is not declared (or Django is not configured, in the tests), it falls back to the
        # environment as before.
        snakeorm = _django_setting("SNAKEORM")
        if snakeorm:
            channels, self._config = debug_config_from_mapping(
                cast("SnakeOrmSettings", snakeorm)
            )
        else:
            channels, self._config = channels_from_env(), SnakeDebugConfig.from_env()
        self._channels = allowed_channels(channels, production=_django_is_production())
        self._buffer = SidecarBuffer()
        warn_unsupported(self._channels, SnakeWebFramework.DJANGO)
        warn_unimplemented(self._channels)

    def __call__(self, request: Any) -> Any:
        """Serve the sidecar, or capture and add the debug to the view's response."""
        path: str = getattr(request, "path", "")
        if (
            path.startswith(_SIDECAR_PREFIX)
            and SnakeDebugChannel.SIDECAR in self._channels
        ):
            return self._serve_sidecar(path, request)
        if not self._channels:
            return self._get_response(request)

        start = perf_counter()
        at = datetime.now(UTC)  # the instant, taken where the wall clock starts
        with capture_queries() as collector:
            response = self._get_response(request)
        report = collector.report().with_wall_ms((perf_counter() - start) * 1000)
        report = report.with_index_hints(index_advice(report, self._config))
        report = report.with_request(
            RequestInfo(
                method=getattr(request, "method", ""),
                path=path,
                status=int(getattr(response, "status_code", 0)),
                at=at,
            )
        )

        token = None
        if SnakeDebugChannel.SIDECAR in self._channels:
            token = new_token()
            self._buffer.store(token, report)
        # The `otel` channel: OUT of `plan_delivery`, which is a pure function that answers
        # `(headers, envelope)` — two things that change the response, which a network send is not.
        # Shared the same way `index_advice` is, and OUTSIDE the streaming `if` below: a
        # `StreamingHttpResponse` has no body to inject a panel into, but it ran the same
        # queries — dropping its trace would hide exactly the endpoints that stream because
        # they are big.
        export_report(report, self._channels)
        delivery = plan_delivery(report, self._channels, token=token)

        # A StreamingHttpResponse has no `.content` (accessing it raises): headers get added to it
        # but the body is not touched — a streaming response is no place for a panel.
        if not getattr(response, "streaming", False):
            content_type = response.get("Content-Type", "")
            new_body = transform_body(
                response.content,
                content_type,
                delivery,
                report,
                self._channels,
                self._config.language,
                _csp_nonce_for(request, self._config),
                token=token,
            )
            if new_body != response.content:
                response.content = new_body
                # Re-seal Content-Length with the REAL length of the already transformed body. If
                # an inner middleware set it earlier (with the HTML WITHOUT the panel), it would be
                # short and the server would truncate the body on the way out: the panel would be
                # lost. Django's test client reads `.content` and does not catch it; a real server
                # (runserver/gunicorn) does.
                response["Content-Length"] = str(len(response.content))
        for name, value in delivery.headers:
            response[name] = value
        return response

    def _serve_sidecar(self, path: str, request: Any) -> Any:
        """Serve `/__snake__/{token}`: the panel page, or the report as JSON if `Accept` asks.

        Django is imported here, lazily. WHAT to answer is decided in `serve_sidecar`, shared with
        the other two adapters; the 404 keeps its own class because that is the status Django reads
        off the response type, not off an argument.
        """
        from django.http import (  # pyright: ignore[reportMissingImports]
            HttpResponse,
            HttpResponseNotFound,
        )

        page = serve_sidecar(
            self._buffer.get(path[len(_SIDECAR_PREFIX) :]),
            accept=_accept_of(request),
            language=self._config.language,
        )
        if page.status == 404:
            return HttpResponseNotFound(page.body)
        return HttpResponse(page.body, content_type=page.content_type)


# --- Django linker: it reads the NATIVE config (settings.DATABASES / settings.SNAKEORM) -------------
# The user works AS ALWAYS (their lifelong `DATABASES`); the translation to `SnakeConnectionConfig`
# is generic and lives in `contrib.config`. Here there is only what is specific to Django: reading
# from `settings`.


def _django_setting(name: str) -> dict[str, Any]:
    """Read a constant off Django's `settings.py`, or `{}` if Django is not configured (tests)."""
    try:
        from django.conf import settings  # pyright: ignore[reportMissingImports]

        return getattr(settings, name, {})
    except Exception:
        return {}


def config_from_django(
    *,
    databases: Mapping[str, SnakeOrmDatabase] | None = None,
    snakeorm: SnakeOrmSettings | None = None,
) -> SnakeOrmConfig:
    """Translate Django's NATIVE config (`settings.DATABASES` + `settings.SNAKEORM`) into the ROOT
    config.

    That way Django CONVERGES on the SAME `SnakeOrmConfig` that Flask/FastAPI build by hand: a
    single normalised shape out of which sessions and the panel config come. The args are injected
    in the tests; in a real app they fall back to `settings` (`{}` if Django is not configured).
    """
    raw_dbs = _django_setting("DATABASES") if databases is None else databases
    raw_settings = _django_setting("SNAKEORM") if snakeorm is None else snakeorm
    connections = {alias: connection_from_mapping(db) for alias, db in raw_dbs.items()}
    return SnakeOrmConfig(
        databases=connections,
        debug=raw_settings.get("DEBUG", ""),
        advise_ms=float(raw_settings.get("ADVISE_MS", DEFAULT_MIN_MS)),
        language=SnakeDebugLanguage.coerce(raw_settings.get("LANG")),
    )


def django_session(
    alias: str = "default",
    *,
    databases: Mapping[str, SnakeOrmDatabase] | None = None,
) -> SnakeSession:
    """Open a session reading Django's `DATABASES` (the `alias`, `"default"` by default).

    A shortcut over `config_from_django(...).open(alias)`. `databases` is injected in the tests (the
    project pattern) so global Django does not have to be configured; in a real app it falls back to
    `settings.DATABASES`.
    """
    return config_from_django(databases=databases).open(alias)
